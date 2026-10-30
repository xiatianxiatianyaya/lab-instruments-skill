"""Explicit, bounded instrument operations. Importing this module never opens hardware."""
from __future__ import annotations
import argparse
import csv
import hashlib
import html
import json
import math
import os
from pathlib import Path
import statistics
import sys
import tempfile
import time
from datetime import datetime

SCOPES = {'DS1202Z-E': 2, 'DHO814': 4}
DMMS = {'DM3058', 'DM3058E'}
SUPPORTED = set(SCOPES) | DMMS | {'DP832A', 'DG1022Z'}

def now():
    return datetime.now().astimezone().isoformat()

def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

def identity(raw):
    parts = raw.strip().split(',')
    if len(parts) < 4:
        raise ValueError('Malformed *IDN? reply: ' + repr(raw))
    return dict(manufacturer=parts[0].strip(), model=parts[1].strip().upper(),
                serial=parts[2].strip(), firmware=','.join(parts[3:]).strip())

def numeric(raw):
    value = float(raw)
    if not math.isfinite(value) or abs(value) >= 1e15:
        raise ValueError('Non-finite/overrange measurement: ' + repr(raw))
    return value

def finite(value, label):
    if not math.isfinite(value):
        raise ValueError(label + ' must be finite')
    return value

def resource_ok(resource):
    u = resource.upper()
    return u.endswith('::INSTR') and u.startswith(('USB', 'TCPIP'))

class ResourceLock:
    """Cross-process lock for this tool; vendor GUI ownership is outside this lock."""
    def __init__(self, resource):
        key = hashlib.sha256(resource.upper().encode()).hexdigest()[:24]
        self.path = Path(tempfile.gettempdir()) / ('lab-instruments-' + key + '.lock')
        self.file = None

    def acquire(self):
        self.file = self.path.open('a+b')
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file = None
            raise RuntimeError('Instrument already owned by another bench.py session')

    def close(self):
        if self.file:
            self.file.close(); self.file = None

class Session:
    def __init__(self, resource, timeout=4000, backend=None, serial=None):
        self.resource, self.timeout, self.backend = resource, timeout, backend
        self.serial = serial
        self.rm = self.dev = None
        self.lock = ResourceLock(resource)
        self.events = []
        self.idn = None

    def __enter__(self):
        if not resource_ok(self.resource):
            raise ValueError('Only explicit USB/TCPIP ::INSTR resources are supported')
        self.lock.acquire()
        try:
            import pyvisa
            self.rm = pyvisa.ResourceManager(self.backend) if self.backend else pyvisa.ResourceManager()
            self.dev = self.rm.open_resource(self.resource, open_timeout=self.timeout)
            self.dev.timeout = self.timeout
            self.dev.read_termination = self.dev.write_termination = '\n'
            self.idn = identity(self.query('*IDN?'))
            if self.serial and self.idn['serial'] != self.serial:
                raise RuntimeError('Instrument serial mismatch')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        try:
            if self.dev:
                self.dev.close()
        finally:
            try:
                if self.rm:
                    self.rm.close()
            finally:
                self.lock.close()

    def query(self, cmd):
        entry = {'time': now(), 'query': cmd}
        self.events.append(entry)
        try:
            value = self.dev.query(cmd).strip(); entry['reply'] = value
            return value
        except Exception as exc:
            entry['error'] = str(exc); raise

    def write(self, cmd):
        entry = {'time': now(), 'write': cmd}
        self.events.append(entry)
        try:
            self.dev.write(cmd)
        except Exception as exc:
            entry['error'] = str(exc); raise
        error = self.query(':SYST:ERR?')
        if int(error.split(',')[0]) != 0:
            raise RuntimeError('Instrument error after ' + cmd + ': ' + error)

    def binary(self, cmd):
        entry = {'time': now(), 'binary_query': cmd}; self.events.append(entry)
        try:
            data = self.dev.query_binary_values(cmd, datatype='B', container=list, expect_termination=False)
            entry['count'] = len(data)
            return data
        except Exception as exc:
            entry['error'] = str(exc); raise

    def require(self, models):
        if self.idn['model'] not in models or 'RIGOL' not in self.idn['manufacturer'].upper():
            raise ValueError('Unsupported identity for operation: ' + repr(self.idn))

def status(s):
    s.require(SUPPORTED)
    model = s.idn['model']
    if model in SCOPES:
        qs = [':TRIG:STAT?', ':TIM:SCAL?', ':ACQ:MDEP?']
        qs += [f':CHAN{ch}:{key}?' for ch in range(1, SCOPES[model]+1)
               for key in ('DISP', 'PROB', 'SCAL', 'OFFS', 'COUP')]
    elif model == 'DP832A':
        qs = [f'{key} CH{ch}' for ch in (1,2,3)
              for key in (':APPL?', ':OUTP?', ':OUTP:MODE?', ':MEAS:ALL?')]
    elif model in DMMS:
        qs = [':FUNCtion?']
    else:
        qs = [q for ch in (1,2) for q in (f':OUTPut{ch}:STATe?', f':OUTPut{ch}:LOAD?',
              f':SOURce{ch}:FUNCtion?', f':SOURce{ch}:FREQuency?',
              f':SOURce{ch}:VOLTage?', f':SOURce{ch}:VOLTage:OFFSet?')]
    # A timeout can leave a late reply queued: abort instead of querying on.
    return {q: s.query(q) for q in qs}

def discover(args):
    result = {'started': now(), 'visa': [], 'probes': {}, 'identity_queried': args.idn}
    rm = None
    try:
        import pyvisa
        rm = pyvisa.ResourceManager(args.backend) if args.backend else pyvisa.ResourceManager()
        result['visa_backend'] = str(rm.visalib)
        resources = [args.resource] if args.resource else list(rm.list_resources())
        result['skipped_resources'] = [r for r in resources if not resource_ok(r)]
        # Close enumeration manager before opening individual sessions.
        rm.close(); rm = None
        for resource in (r for r in resources if resource_ok(r)):
            row = {'resource': resource}; result['visa'].append(row)
            if args.idn:
                try:
                    with Session(resource, args.timeout, args.backend) as s:
                        row['identity'] = s.idn
                        row['supported'] = s.idn['model'] in SUPPORTED and 'RIGOL' in s.idn['manufacturer'].upper()
                except Exception as exc:
                    row['error'] = str(exc)
    except Exception as exc:
        result['visa_error'] = str(exc)
    finally:
        if rm: rm.close()
    if args.probes:
        j = None
        try:
            import pylink
            j = pylink.JLink()
            result['probes']['jlink'] = [
                {'serial': int(p.SerialNumber), 'product': bytes(p.acProduct).decode(errors='replace').rstrip('\x00')}
                for p in j.connected_emulators()]
        except Exception as exc:
            result['probes']['jlink_error'] = str(exc)
        finally:
            if j: j.close()
        try:
            from pyocd.core.helpers import ConnectHelper
            result['probes']['cmsis_dap'] = [
                {'id': p.unique_id, 'description': p.description}
                for p in ConnectHelper.get_all_connected_probes(blocking=False)
                if 'cmsis' in type(p).__module__.lower()]
        except Exception as exc:
            result['probes']['cmsis_dap_error'] = str(exc)
    result['finished'] = now()
    save(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

def dmm_read(s, args, report):
    s.require(DMMS)
    command = ':MEASure:' + ('VOLTage:DC?' if args.function == 'DCV' else 'CURRent:DC?')
    report.update(unit='V' if args.function == 'DCV' else 'A', samples=[],
                  wiring=args.wiring, range_speed='Front-panel settings; not verified by this script')
    report['function_before'] = s.query(':FUNCtion?')
    for n in range(args.count):
        raw = s.query(command)
        row = {'time': now(), 'raw': raw}; report['samples'].append(row)
        row['value'] = numeric(raw)
        print(f'{n+1}/{args.count}: {raw} {report["unit"]}', flush=True)
        if n+1 < args.count: time.sleep(args.interval)
    values = [x['value'] for x in report['samples']]
    report.update(mean=statistics.mean(values), minimum=min(values), maximum=max(values),
                  repeated_identical=len(values)>1 and len(set(values))==1)
    report['function_after'] = s.query(':FUNCtion?')
    if report['repeated_identical']:
        report['note'] = 'All readings identical; check freshness/HOLD if inconsistent with known input changes.'
    path = Path(args.out).with_suffix('.csv'); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w=csv.writer(f); w.writerow(['time','raw','value_'+report['unit']])
        w.writerows((x['time'],x['raw'],x['value']) for x in report['samples'])
    report['csv'] = str(path.resolve())

def decode_waveform(preamble, raw):
    p = [float(x) for x in preamble.split(',')]
    if len(p)!=10 or not all(math.isfinite(x) for x in p) or p[0]!=0 or p[4]<=0 or p[7]<=0:
        raise ValueError('Invalid BYTE waveform preamble')
    if p[2]!=int(p[2]) or len(raw)!=int(p[2]) or not 2<=len(raw)<=250000:
        raise ValueError('Incomplete/oversize waveform')
    return [((i-p[6])*p[4]+p[5], (v-p[8]-p[9])*p[7]) for i,v in enumerate(raw)]

def waveform_svg(path, points, label):
    ts, vs = zip(*points); t0,t1=ts[0],ts[-1]; v0,v1=min(vs),max(vs)
    if v1==v0: v0-=.001; v1+=.001
    # Preserve min/max per pixel bucket so short spikes survive plot downsampling.
    stride=max(1, math.ceil(len(points)/900)); sampled=[]
    for i in range(0,len(points),stride):
        bucket=points[i:i+stride]
        sampled.extend(sorted([min(bucket,key=lambda p:p[1]),max(bucket,key=lambda p:p[1])]))
    coord=' '.join(f'{70+(t-t0)/(t1-t0)*880:.2f},{330-(v-v0)/(v1-v0)*270:.2f}' for t,v in sampled)
    text=html.escape(f'{label} | {t0:.6g} .. {t1:.6g} s | {min(vs):.6g} .. {max(vs):.6g} V')
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="400" viewBox="0 0 1000 400"><rect x="1" y="1" width="998" height="398" fill="white" stroke="black"/><text x="35" y="30" font-size="16">{text}</text><path d="M70 60V330H950" fill="none" stroke="black"/><text x="450" y="380">Time (s)</text><text x="10" y="195">V</text><polyline points="{coord}" fill="none" stroke="#075ca8" stroke-width="1"/></svg>', encoding='utf-8')

def scope_export(s,args,report):
    s.require(SCOPES)
    if not 1<=args.channel<=SCOPES[s.idn['model']]: raise ValueError('Channel outside model range')
    report['before']=status(s)
    state=report['before'][':TRIG:STAT?'].upper()
    if state!='STOP':
        if not args.stop: raise RuntimeError('Acquisition not STOP; use --stop only to authorize freezing current data')
        s.write(':STOP')
        if s.query(':TRIG:STAT?').upper()!='STOP': raise RuntimeError('Scope did not stop')
    report.update(acquisition='Existing stopped record; no fresh trigger claimed', wiring=args.wiring,
                  changed_settings=['waveform source','waveform mode RAW','waveform format BYTE','waveform transfer window'],
                  stopped_by_script=(state!='STOP'))
    for cmd in (f':WAV:SOUR CHAN{args.channel}',':WAV:MODE RAW',':WAV:FORM BYTE',':WAV:STAR 1'):
        s.write(cmd)
    pre=s.query(':WAV:PRE?'); report['preamble']=pre
    p=[float(x) for x in pre.split(',')]
    if len(p)!=10 or not all(math.isfinite(x) for x in p) or p[0]!=0 or p[2]!=int(p[2]) or not 2<=p[2]<=250000:
        raise ValueError('Unsupported/empty/oversize BYTE record; reduce memory depth explicitly')
    n=int(p[2]);raw=[]; report['raw_byte']=raw
    for start in range(1,n+1,100000):
        stop=min(start+99999,n)
        s.write(f':WAV:STAR {start}');s.write(f':WAV:STOP {stop}')
        chunk=s.binary(':WAV:DATA?');raw.extend(chunk)
        if len(chunk)!=stop-start+1: raise RuntimeError('Incomplete waveform block')
    points=decode_waveform(pre,raw)
    path=Path(args.out).with_suffix('.csv');path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['time_s','voltage_V','raw_byte']);w.writerows((t,v,b) for (t,v),b in zip(points,raw))
    svg=path.with_suffix('.svg');waveform_svg(svg,points,s.idn['model']+f' CH{args.channel}')
    report.update(points=n,csv=str(path.resolve()),svg=str(svg.resolve()),after_trigger=s.query(':TRIG:STAT?'))

def power_plan(args):
    for name in ('voltage','current','max_voltage','max_current'): finite(getattr(args,name),name)
    if not 0<=args.voltage<=args.max_voltage or not 0<args.current<=args.max_current:
        raise ValueError('Requested setpoint outside supplied DUT limits')
    if args.channel not in (1,2,3):raise ValueError('DP832A channel must be 1, 2 or 3')
    commands=[f':APPL CH{args.channel},{args.voltage:.9g},{args.current:.9g}']
    if args.output!='keep':commands.append(f':OUTP CH{args.channel},{args.output.upper()}')
    return commands

def output_normalize(raw):
    v=raw.strip().strip('"').upper()
    if v in ('1','ON'):return 'ON'
    if v in ('0','OFF'):return 'OFF'
    raise ValueError('Unknown output state: '+raw)

def supply_set(s,args,report):
    s.require({'DP832A'});commands=power_plan(args);ch=args.channel
    report['before']={q:s.query(q) for q in (f':APPL? CH{ch}',f':OUTP? CH{ch}')}
    before_output=output_normalize(report['before'][f':OUTP? CH{ch}'])
    s.write(commands[0])
    applied=s.query(f':APPL? CH{ch}');report['applied']=applied
    fields=applied.replace('"','').split(',');v,i=map(float,fields[-2:])
    if not math.isfinite(v) or not math.isfinite(i) or abs(v-args.voltage)>.001 or abs(i-args.current)>.001:
        raise RuntimeError('Power setpoint readback mismatch; output enable not attempted')
    if len(commands)>1:s.write(commands[1])
    after=s.query(f':OUTP? CH{ch}');report['output_after']=after
    expected=before_output if args.output=='keep' else args.output.upper()
    if output_normalize(after)!=expected:raise RuntimeError('Power output state mismatch')
    report['terminal_measurement_V_A_W']=s.query(f':MEAS:ALL? CH{ch}')
    report['regulation_mode']=s.query(f':OUTP:MODE? CH{ch}')
    report['note']='Terminal measurement, not independent DUT-pin voltage. No automatic rollback.'

def parser():
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='action',required=True)
    for action in ('discover','status','dmm-read','scope-export','supply-set'):
        q=subs.add_parser(action)
        q.add_argument('--resource',required=action!='discover')
        q.add_argument('--backend');q.add_argument('--serial');q.add_argument('--timeout',type=int,default=4000)
        q.add_argument('--out',required=True)
        if action=='discover':q.add_argument('--idn',action='store_true');q.add_argument('--probes',action='store_true')
        if action not in ('discover','status'):q.add_argument('--apply',action='store_true')
        if action in ('dmm-read','scope-export'):q.add_argument('--wiring',default='unknown')
        if action=='dmm-read':
            q.add_argument('--function',choices=['DCV','DCI'],required=True)
            q.add_argument('--count',type=int,default=20);q.add_argument('--interval',type=float,default=.5)
        if action=='scope-export':
            q.add_argument('--channel',type=int,required=True);q.add_argument('--stop',action='store_true')
        if action=='supply-set':
            q.add_argument('--channel',type=int,required=True)
            for key in ('voltage','current','max-voltage','max-current'):q.add_argument('--'+key,type=float,required=True)
            q.add_argument('--output',choices=['keep','on','off'],default='keep')
    return p

def main(argv=None):
    args=parser().parse_args(argv)
    if not 100<=args.timeout<=60000:raise ValueError('Timeout must be 100..60000 ms')
    if args.action=='discover':return discover(args)
    if args.action=='dmm-read' and (not 1<=args.count<=10000 or not math.isfinite(args.interval) or not 0<=args.interval<=60):
        raise ValueError('Count/interval out of bounds')
    commands=power_plan(args) if args.action=='supply-set' else None
    if args.action!='status' and not args.apply:
        print(json.dumps({'dry_run':True,'operation':vars(args),'commands':commands,'notice':'No device opened; add --apply only within authorized wiring and limits'},ensure_ascii=False,indent=2))
        return 0
    report={'started':now(),'operation':vars(args),'status':'started'}
    report_path=Path(args.out) if args.action in ('status','supply-set') else Path(args.out).with_suffix('.json')
    if report_path.exists():raise FileExistsError('Use a new output path to retain previous results: '+str(report_path))
    s=Session(args.resource,args.timeout,args.backend,args.serial)
    code=0
    try:
        with s:
            report['identity']=s.idn
            if args.action=='status':report['readings']=status(s)
            elif args.action=='dmm-read':dmm_read(s,args,report)
            elif args.action=='scope-export':scope_export(s,args,report)
            elif args.action=='supply-set':supply_set(s,args,report)
            report['status']='complete'
    except Exception as exc:
        report.update(status='failed',error=str(exc),warning='Do not assume settings were restored after failure.')
        code=1
    finally:
        report.update(finished=now(),io=s.events)
        save(report_path,report)
    print(json.dumps({'status':report['status'],'report':str(report_path.resolve()),'error':report.get('error')},ensure_ascii=False))
    return code

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:print(str(exc),file=sys.stderr);sys.exit(2)
