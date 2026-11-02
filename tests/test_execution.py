"""Independent counterexamples for manuscript Sections VI-A, V and VII-A."""
import itertools
import math
import random
import unittest
import importlib.util
from pathlib import Path
from fractions import Fraction

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))

from dcnc_sim.models import Commodity, DistributedComputingNetwork, ServiceDAG
from dcnc_sim.mapping import NearestToSourceSolver, ValidMapping
from dcnc_sim.physical import PhysicalNetwork, ComputeTask, LinkQueueItem
from dcnc_sim.wireless import AlwaysOnProcess
from dcnc_sim.interference import (PrimaryInterferenceActivationPolicy,
                                   EnumeratedActivationPolicy)


def network(nodes, edges=(), capacity=1.0):
    net = DistributedComputingNetwork('test')
    for node in nodes:
        net.node_roles[node] = 'COMPUTE'
        net.node_capacities[node] = capacity
        net.out_adj[node] = set()
        net.in_adj[node] = set()
    for u, v in edges:
        net.edge_capacities[u, v] = capacity
        net.out_adj[u].add(v)
        net.in_adj[v].add(u)
    return net


def dag(nodes, edges=(), workloads=None):
    d = ServiceDAG('test')
    for name, kind in nodes.items():
        d.node_types[name] = kind
        d.node_r[name] = (workloads or {}).get(name, 1.0)
        d.node_in[name] = d.node_out[name] = 1.0
        d.out_adj[name] = set()
        d.in_adj[name] = set()
    for u, v in edges:
        d.edge_xi[u, v] = 1.0
        d.out_adj[u].add(v)
        d.in_adj[v].add(u)
    d.validate()
    return d


class ExecutionTests(unittest.TestCase):
    def test_compute_nonpreemption(self):
        net = network(['u'])
        p = PhysicalNetwork(net, AlwaysOnProcess(net))
        d = dag({'A':'function'}, workloads={'A':3.0})
        a = ComputeTask('c','first','A','u',3.0,5,ValidMapping({'A':'u'}),d,0)
        b = ComputeTask('c','later','A','u',3.0,2,ValidMapping({'A':'u'}),d,0)
        p._enqueue_compute_task(a)
        p.serve_one_slot()
        p._enqueue_compute_task(b)
        p.serve_one_slot()
        self.assertEqual((a.size_remaining,b.size_remaining), (1.0,3.0))
        p.serve_one_slot()
        self.assertEqual(p.node_queues['u'], [b])

    def test_link_nonpreemption_survives_off_slot(self):
        net = network(['u','v','w'], [('u','v'),('v','w')])
        p = PhysicalNetwork(net, AlwaysOnProcess(net))
        a = LinkQueueItem('c','first',('A','B'),[('u','v'),('v','w')],0,3,3,5,0)
        b = LinkQueueItem('c','later',('A','B'),[('u','v')],0,3,3,2,0)
        p._enqueue_link_item(a)
        p.serve_one_slot()
        p._enqueue_link_item(b)
        p.set_activated_edges(set())
        p.serve_one_slot()
        self.assertEqual(a.size_remaining,2)
        p.set_activated_edges({('u','v')})
        p.serve_one_slot()
        self.assertEqual((a.size_remaining,b.size_remaining), (1,3))

    def test_remaining_capacity_serves_next_eligible_job(self):
        net = network(['u'])
        p = PhysicalNetwork(net, AlwaysOnProcess(net))
        d = dag({'A':'function'}, workloads={'A':0.4})
        for job in ['a','b','c']:
            p._enqueue_compute_task(ComputeTask('c',job,'A','u',0.4,0,ValidMapping({'A':'u'}),d,0))
        p.serve_one_slot()
        self.assertEqual(len(p.node_queues['u']),1)
        self.assertAlmostEqual(p.node_queues['u'][0].size_remaining,0.2)

    def chain(self, multihop=False):
        edges = [('s','m'),('m','u')] if multihop else [('s','u')]
        net = network(['s','m','u'],edges,capacity=2)
        d = dag({'A':'source','B':'sink'},[('A','B')],{'A':0.5,'B':0.5})
        c = Commodity('c',d,{'A':'s'},{'B':'u'})
        m = ValidMapping({'A':'u','B':'u'})
        m.set_edge_path((('S','A'),'A'),edges)
        m.set_edge_path(('A','B'),[])
        m.set_edge_path(('B',('D','B')),[])
        p = PhysicalNetwork(net,AlwaysOnProcess(net))
        p.register_job('j',m,d,c,0)
        p.inject_one_unit('j')
        return p

    def test_transmission_to_compute_and_empty_path_successor_deferred(self):
        p = self.chain()
        p.serve_one_slot()
        self.assertEqual([(x.func,x.size_remaining,x.hop) for x in p.node_queues['u']],[('A',0.5,1)])
        p.set_time(1); p.serve_one_slot()
        self.assertEqual([(x.func,x.size_remaining,x.hop) for x in p.node_queues['u']],[('B',0.5,2)])
        self.assertEqual(p.completed_service_units,0)
        p.set_time(2); p.serve_one_slot()
        self.assertEqual(p.completed_service_units,1)
        self.assertEqual(p.total_backlog(),0)

    def test_next_link_waits_until_next_slot(self):
        p = self.chain(multihop=True)
        p.serve_one_slot()
        self.assertEqual(p.link_queues['m','u'][0].size_remaining,1)
        self.assertFalse(p.node_queues['u'])
        p.set_time(1); p.serve_one_slot()
        self.assertEqual(p.node_queues['u'][0].hop,2)

    def test_empty_ingress_is_resolved_before_service(self):
        p = self.chain()
        p.link_queues['s','u'].clear()
        item = LinkQueueItem('c','j',(('S','A'),'A'),[],0,1,1,0,0)
        p._enqueue_link_item(item)
        p.serve_one_slot()
        self.assertEqual(p.node_queues['u'][0].func,'B')
        self.assertEqual(p.node_queues['u'][0].hop,1)

    def test_merge_waits_for_all_inputs_then_next_slot(self):
        net = network(['u','v'],capacity=1)
        d = dag({'A':'source','B':'source','C':'sink'},[('A','C'),('B','C')],{'A':1,'B':2,'C':1})
        c = Commodity('c',d,{'A':'u','B':'v'},{'C':'u'})
        # For this synchronization test the two sources execute co-located.
        m = ValidMapping({'A':'u','B':'u','C':'u'})
        c.src_nodes['B']='u'
        p = PhysicalNetwork(net,AlwaysOnProcess(net))
        p.register_job('j',m,d,c,0); p.inject_one_unit('j')
        for t in range(3):
            p.set_time(t); p.serve_one_slot()
            self.assertEqual(p.completed_service_units,0)
        self.assertEqual([(x.func,x.hop) for x in p.node_queues['u']],[('C',1)])
        p.set_time(3); p.serve_one_slot()
        self.assertEqual(p.completed_service_units,1)

    def test_fifo_ignores_grade_when_starting_new_service(self):
        net=network(['u']); p=PhysicalNetwork(net,AlwaysOnProcess(net),scheduler='fifo')
        d=dag({'A':'function'},workloads={'A':2})
        for job,grade in [('a',8),('b',0)]:
            p._enqueue_compute_task(ComputeTask('c',job,'A','u',2,grade,ValidMapping({'A':'u'}),d,0))
        p.serve_one_slot()
        self.assertEqual([x.size_remaining for x in p.node_queues['u']],[1,2])

    def test_cts_uses_immediate_placed_predecessor(self):
        edges=[('u1','u2'),('u2','u3'),('u3','u4'),('u4','u5')]
        net=network(['u1','u2','u3','u4','u5'],edges+[(v,u) for u,v in edges])
        d=dag({'A':'source','B':'function','C':'sink'},[('A','B'),('B','C')])
        c=Commodity('c',d,{'A':'u1'},{'C':'u5'},{'A':['u1'],'B':['u5'],'C':['u2','u4']})
        result=NearestToSourceSolver(net).compute(d,c,{}, {})
        self.assertEqual(result.assign['C'],'u4')
        self.assertEqual(result.path_for(('B','C')),[('u5','u4')])


class ActivationTests(unittest.TestCase):
    def test_non_tie_cannot_be_overturned_by_huge_physical_backlog(self):
        edges=[('a','b'),('a','c')]; net=network(['a','b','c'],edges)
        policies=[PrimaryInterferenceActivationPolicy(),EnumeratedActivationPolicy([{e} for e in edges])]
        for gap in [0.0001,math.ulp(10.0)]:
            for policy in policies:
                result=policy.select_active_edges(net,{edges[0]:10+gap,edges[1]:10},net.edge_capacities,{edges[1]:1e100})
                self.assertEqual(result,{edges[0]})

    def test_secondary_breaks_only_exact_primary_ties(self):
        edges=[('a','b'),('a','c')]; net=network(['a','b','c'],edges)
        for policy in [PrimaryInterferenceActivationPolicy(),EnumeratedActivationPolicy([{e} for e in edges])]:
            self.assertEqual(policy.select_active_edges(net,{e:10 for e in edges},net.edge_capacities,{edges[1]:2}),{edges[1]})

    def test_matching_against_independent_fraction_enumeration(self):
        rng=random.Random(29); nodes=list('abcdef')
        for trial in range(120):
            edges=rng.sample([(u,v) for u in nodes for v in nodes if u!=v],9)
            net=network(nodes,edges)
            cap={e:rng.choice([0.,0.1,0.3,1.,2.]) for e in edges}
            q={e:rng.choice([0.,math.ulp(1.),0.1,1.,1.0000000000000002,5.]) for e in edges}
            physical={e:rng.choice([0.,0.01,1.,1e20]) for e in edges}
            feasible=[]
            for mask in range(1<<len(edges)):
                candidate={e for i,e in enumerate(edges) if mask & (1<<i)}
                endpoints=[n for e in candidate for n in e]
                if len(endpoints)==len(set(endpoints)) and all(cap[e]>0 for e in candidate):
                    feasible.append(candidate)
            def score(s):
                return (sum(Fraction(q[e])*Fraction(cap[e]) for e in s),
                        sum(Fraction(physical[e])*Fraction(cap[e]) for e in s),len(s))
            wanted=max(map(score,feasible))
            for policy in [PrimaryInterferenceActivationPolicy(),EnumeratedActivationPolicy(feasible)]:
                result=policy.select_active_edges(net,q,cap,physical)
                self.assertIn(result,feasible)
                self.assertEqual(score(result),wanted,(trial,policy))


class IndependentFifoTests(unittest.TestCase):
    def test_nonpreemption_and_work_conservation_with_fractional_workloads(self):
        path=Path(__file__).resolve().parents[1]/'scripts/fifo/sim_exact.py'
        spec=importlib.util.spec_from_file_location('fifo_test',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.simulate(lam=0.5,seed=3,policy='NTO',T=2000,M0=0,
                              work=(0.13,2.1,0.17,0.19,0.23,2.1),check_partials=True)
        self.assertTrue(result['conservation_ok'])
        for node in ['u1','v1']:
            self.assertLessEqual(result['max_partial_jobs_'+node],1)
            self.assertEqual(result['idle_nonempty_'+node],0)
            self.assertEqual(result['service_reconciliation_'+node],0)


if __name__=='__main__':
    unittest.main(verbosity=2)
