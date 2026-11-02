"""Request censoring, seed weights and the published display-selection contract."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from delay_lower_bound import run_lower_bound, summarize_lower_bounds


def fixture(n=2, completed=1, delay_sum=10, ages=20, seed=1):
    job=dict(id='fixture',kind='main',params=dict(case='test',policy='DCNC-DAG',solver='exact_dp',
                                               fixed_k=1,rate=1,seed=seed,slots=100))
    record=dict(result={},stats=dict(total_service_units=n,completed_service_units=completed,
                pending_service_units=n-completed,avg_service_delay_completed=delay_sum/completed if completed else 0),
                audit=dict(completed_request_delay_sum=delay_sum,pending_registered_request_age_sum=ages))
    return job, record


class LowerBoundTests(unittest.TestCase):
    def test_completed_plus_unfinished_ages_uses_all_arrivals(self):
        job, record=fixture()
        original=copy.deepcopy(record)
        row=run_lower_bound(job,record)
        self.assertEqual(row['mean_request_delay_lower_bound'],15)
        self.assertEqual(row['mean_completed_request_delay'],10)
        self.assertEqual(record,original)

    def test_no_completions_still_has_a_lower_bound(self):
        row=run_lower_bound(*fixture(completed=0,delay_sum=0,ages=50))
        self.assertEqual(row['mean_request_delay_lower_bound'],25)
        self.assertIsNone(row['mean_completed_request_delay'])

    def test_all_requests_complete_matches_completed_mean(self):
        row=run_lower_bound(*fixture(completed=2,delay_sum=18,ages=0))
        self.assertEqual(row['mean_request_delay_lower_bound'],9)

    def test_zero_arrivals_undefined_and_not_silently_dropped(self):
        empty=run_lower_bound(*fixture(n=0,completed=0,delay_sum=0,ages=0))
        other=run_lower_bound(*fixture(seed=2))
        summary=summarize_lower_bounds([empty,other])[0]
        self.assertEqual(summary['seeds'],2)
        self.assertIsNone(summary['mean_request_delay_lower_bound'])
        self.assertIsNone(summary['mean_completion_ratio'])

    def test_missing_unfinished_ages_is_an_error(self):
        job,record=fixture()
        del record['audit']['pending_registered_request_age_sum']
        with self.assertRaisesRegex(ValueError,'Missing request-delay lower-bound'):
            run_lower_bound(job,record)

    def test_bad_conservation_and_age_sum_fail(self):
        for n,completed,delay,ages in [(1,2,18,0),(2,1,10,0),(2,1,10,101),(2,0,1,50)]:
            with self.subTest(values=(n,completed,delay,ages)),self.assertRaises(ValueError):
                run_lower_bound(*fixture(n,completed,delay,ages))

    def test_seed_mean_and_sem_do_not_pool_requests(self):
        rows=[run_lower_bound(*fixture(n=2,completed=2,delay_sum=20,ages=0,seed=1)),
              run_lower_bound(*fixture(n=20,completed=20,delay_sum=600,ages=0,seed=2))]
        summary=summarize_lower_bounds(rows)[0]
        self.assertEqual(summary['mean_request_delay_lower_bound'],20)
        self.assertEqual(summary['lower_bound_se'],10)
        with self.assertRaisesRegex(ValueError,'Duplicate seed'):
            summarize_lower_bounds([rows[0],rows[0]])

    def test_final_tail_selection_restores_random_random_heuristic(self):
        jobs=json.loads((ROOT/'inputs/experiments.json').read_text())
        config=json.loads((ROOT/'inputs/plots/policy_map.json').read_text())
        counts=config['tail_trim']
        self.assertEqual(sum(sum(v.values()) for v in counts.values()),65)
        rates=sorted({j['params']['rate'] for j in jobs if j['kind']=='main'
                      and j['params']['case']=='r6_random' and j['params']['solver']=='greedy'})
        selected=rates[:-counts['r6_random']['greedy']]
        self.assertEqual(selected[-1],.6957)
        self.assertEqual(rates[-1],.7593)


if __name__=='__main__':
    unittest.main()
