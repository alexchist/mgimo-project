import unittest
from benchmark import HERE, read, messages, schedule, grades, parse_answer

class Protocol(unittest.TestCase):
    def test_pairing(self):
        cases=read(HERE/'cases.json'); ks=read(HERE/'keys.json'); self.assertEqual(len(ks),8)
        self.assertEqual(len(cases),10); self.assertTrue(all(len(x)==4 for x in ks.values()))
        for c in cases:
            a,b=messages(c,False),messages(c,True); self.assertEqual(a[1],b[1]);self.assertTrue(b[0]['content'].startswith(a[0]['content']));self.assertNotEqual(a[0],b[0]); self.assertNotIn('keys.json',str(b))
        jobs=list(schedule(['X','Y','Z'],2)); self.assertEqual(len(jobs),120)
        for m in ['X','Y','Z']:
            groups=[[ (x[1]['id'],x[3]) for x in jobs if x[0]==m and x[2]==r][::2] for r in (1,2)]; self.assertEqual(sum(a=='B' for _,a in groups[0]),5)
            self.assertTrue(all(dict(groups[1])[i]!=a for i,a in groups[0]))
    def test_grades(self):
        k={'n':1,'data':None,'ok':True}; row=lambda s:{'status':'ok','answer':s}
        self.assertEqual(grades(row('```json\n{"n":1.0,"data":null,"ok":true}\n```'),k),[True]*3)
        self.assertEqual(grades(row('{"n":true,"ok":1}'),k),[False]*3);self.assertIsNone(parse_answer('{"n":1,"n":0}'))

if __name__=='__main__':unittest.main()
