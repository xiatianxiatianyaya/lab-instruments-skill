import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bench',ROOT/'lab-instruments/scripts/bench.py')
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)

class Fake:
    def __init__(self,model='DP832A',reply=None):
        self.idn={'manufacturer':'RIGOL TECHNOLOGIES','model':model,'serial':'SIMULATED','firmware':'mock'}
        self.reply=reply or {};self.writes=[];self.events=[]
    def require(self,models):b.Session.require(self,models)
    def query(self,cmd):
        value=self.reply[cmd]
        if isinstance(value,Exception):raise value
        if isinstance(value,list):return value.pop(0)
        return value
    def write(self,cmd):self.writes.append(cmd)
    def __enter__(self):return self
    def __exit__(self,*_):pass

class BenchTests(unittest.TestCase):
    def power_args(self,extra=()):
        return b.parser().parse_args(['supply-set','--resource','USB0::1::2::SIM::INSTR','--out','unused.json',
          '--channel','1','--voltage','3.3','--current','.1','--max-voltage','5','--max-current','.1',*extra])

    def test_dry_run_never_opens_hardware(self):
        with patch.object(b,'Session',side_effect=AssertionError('opened hardware')),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(b.main(['dmm-read','--resource','USB0::1::2::SIM::INSTR','--function','DCI','--out','unused']),0)

    def test_limits_reject_nan_and_excess_before_writes(self):
        for value in (float('nan'),float('inf'),5.1,-1):
            args=self.power_args();args.voltage=value
            with self.assertRaises(ValueError):b.power_plan(args)

    def test_keep_output_does_not_emit_output_command(self):
        args=self.power_args();self.assertEqual(len(b.power_plan(args)),1)
        f=Fake(reply={':APPL? CH1':['CH1,5,0.1','CH1,3.3,0.1'],':OUTP? CH1':'OFF',
          ':MEAS:ALL? CH1':'0,0,0',':OUTP:MODE? CH1':'CV'})
        r={};b.supply_set(f,args,r)
        self.assertFalse(any(':OUTP ' in c for c in f.writes))
        self.assertEqual(r['output_after'],'OFF')

    def test_bad_setpoint_readback_never_enables_output(self):
        f=Fake(reply={':APPL? CH1':['CH1,5,0.1','CH1,4.1,0.1'],':OUTP? CH1':'OFF'})
        with self.assertRaises(RuntimeError):b.supply_set(f,self.power_args(['--output','on']),{})
        self.assertEqual(len(f.writes),1)

    def test_wrong_model_no_writes(self):
        f=Fake(model='DS1202Z-E')
        with self.assertRaises(ValueError):b.supply_set(f,self.power_args(),{})
        self.assertEqual(f.writes,[])

    def test_invalid_measurements_rejected(self):
        for raw in ('nan','inf','9e15','-9e15','not a number'):
            with self.assertRaises(ValueError):b.numeric(raw)
        self.assertAlmostEqual(b.numeric('5.2E-6'),.0000052)

    def test_waveform_scaling_not_double_probe_multiplier(self):
        points=b.decode_waveform('0,0,3,1,0.001,-0.001,0,0.01,100,28',[128,129,130])
        self.assertEqual(points,[(-.001,0.0),(0.0,.01),(.001,.02)])

    def test_partial_waveform_rejected(self):
        with self.assertRaises(ValueError):b.decode_waveform('0,0,3,1,1,0,0,1,0,0',[1,2])

    def test_running_scope_requires_explicit_stop(self):
        args=b.parser().parse_args(['scope-export','--resource','USB0::1::2::SIM::INSTR','--out','unused','--channel','1','--apply'])
        f=Fake(model='DS1202Z-E')
        with patch.object(b,'status',return_value={':TRIG:STAT?':'RUN'}):
            with self.assertRaises(RuntimeError):b.scope_export(f,args,{})
        self.assertEqual(f.writes,[])

    def test_query_timeout_stops_sequence(self):
        class Device:
            def query(self,cmd):raise TimeoutError('mock timeout')
        s=b.Session('USB0::1::2::SIM::INSTR');s.idn={'manufacturer':'RIGOL','model':'DP832A'};s.dev=Device()
        with self.assertRaises(TimeoutError):b.status(s)
        self.assertEqual(len(s.events),1)

    def test_partial_dmm_failure_keeps_valid_samples_and_error(self):
        f=Fake(model='DM3058E',reply={':FUNCtion?':'DCI',':MEASure:CURRent:DC?':['5.2e-6','9e15']})
        with tempfile.TemporaryDirectory() as d,patch.object(b,'Session',return_value=f),contextlib.redirect_stdout(io.StringIO()):
            target=str(Path(d)/'reading')
            rc=b.main(['dmm-read','--resource','USB0::1::2::SIM::INSTR','--function','DCI','--count','2','--interval','0','--out',target,'--apply'])
            r=json.loads(Path(target+'.json').read_text(encoding='utf-8'))
            self.assertEqual(rc,1);self.assertEqual(r['status'],'failed')
            self.assertAlmostEqual(r['samples'][0]['value'],5.2e-6)
            self.assertEqual(r['samples'][1]['raw'],'9e15');self.assertNotIn('mean',r)

    def test_same_resource_lock_blocks_second_owner(self):
        a=b.ResourceLock('USB0::1::2::UNITTEST::INSTR');c=b.ResourceLock('USB0::1::2::UNITTEST::INSTR')
        try:
            a.acquire()
            with self.assertRaises(RuntimeError):c.acquire()
        finally:a.close();c.close()

if __name__=='__main__':unittest.main()
