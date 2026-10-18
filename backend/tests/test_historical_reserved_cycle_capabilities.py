"""Focused copied-input mutation regression; old stage scenarios are never run."""
import hashlib
from pathlib import Path
import unittest

from backend.agents.trading.desk import paper
from backend.market import historical_broker_checkpoint as codec
from backend.market import historical_reserved_native_io as reserved_io
from backend.market.historical_packet_store import StorePause
from backend.tests import test_historical_reserved_cycle_stages as setup

PHYSICAL_OBSERVATIONS = setup.PHYSICAL_OBSERVATIONS
ACTUAL_KILL_FILES = []
CALLS = []


# Mutate the detached order after valid observation to expose a later-effect binding gap.
def changing_program(*, phase, inputs, effects):
    CALLS.append(phase)
    if phase == 'DECISION_FROZEN':
        return {'order': inputs['candidate']}
    effects.observe()
    effects.declaration['order']['qty'] += 1
    try:
        effects.submit()
    except ValueError:
        pass
    effects.latch()
    raise AssertionError('Changed declaration continued')


# Delegate the unchanged valid capabilities under this separate source-bound executor.
def valid_program(*, phase, inputs, effects):
    CALLS.append(phase)
    return setup.program(phase=phase, inputs=inputs, effects=effects)


# Use only prior setup helpers with two new focused assertions, never inherited tests.
class ReservedCycleCapabilityTests(unittest.TestCase):
    # Allocate a fresh private synthetic account and original physically initialized pools.
    def setUp(self):
        self.case = setup.ReservedCycleStagesTests()
        self.case.setUp()

    # Preserve every original CAS allocation field while retaining the private account.
    def tearDown(self):
        self.case.tearDown()

    # Bind one exact new callback source before any birth, preparation or stage work.
    def prepare(self, program):
        case = self.case
        case.io = reserved_io.SyntheticNativeIO(case.writer, program,
            trade_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        case.prepare_decision()
        return case

    # Capture state that successful original recovery must leave byte-for-byte unchanged.
    def retained(self, case):
        return (paper.state_path(case.nightly.root).read_bytes(),
            codec.encode(case.client, **case.nightly.pins()), (case.writer.root / 'control').read_bytes(),
            (case.raw.root / 'control').read_bytes(), (case.cas.root / 'control').read_bytes(),
            case.store.snapshot(), len(CALLS), len(setup.CALLS))

    # Refuse an altered order after the valid observation, with no save/latch or retry.
    def test_mutation_between_effects_pauses_before_changed_order(self):
        case = self.prepare(changing_program)
        head = case.store.snapshot()['head']
        before = (paper.state_path(case.nightly.root).read_bytes(),
            (case.writer.root / 'control').read_bytes(), (case.raw.root / 'control').read_bytes())
        with self.assertRaises(ValueError):
            case.stage._run('SUBMISSION_CAPTURED', case.submission)
        self.assertEqual([row['qty'] for row in case.client.open_orders()], [])
        self.assertEqual(case.client.clock()['timestamp'], case.submission['observe']['at'])
        self.assertEqual(case.cas._control()['groups'][-1]['status'], 'PAUSED')
        self.assertEqual(case.store.snapshot()['head'], head)
        self.assertFalse((case.nightly.root / 'synthetic-latch' / (case.stage.session + '.json')).exists())
        self.assertEqual(before, (paper.state_path(case.nightly.root).read_bytes(),
            (case.writer.root / 'control').read_bytes(), (case.raw.root / 'control').read_bytes()))
        with self.assertRaises(ValueError):
            case.io.save(case.nightly.root, paper.load_state(case.nightly.root))
        with self.assertRaises(ValueError):
            case.io.evidence()
        calls = len(CALLS)
        with self.assertRaisesRegex(StorePause, 'never replay'):
            case.stage._run('SUBMISSION_CAPTURED', case.submission)
        self.assertEqual(len(CALLS), calls)
        self.assertEqual(case.inventory(), case.before)

    # Preserve the complete valid preparation/decision/submission path and original recovery.
    def test_unchanged_inputs_commit_and_recover_without_more_effects(self):
        case = self.prepare(valid_program)
        result = case.stage._run('SUBMISSION_CAPTURED', case.submission)
        self.assertEqual([row['qty'] for row in case.client.open_orders()], ['5'])
        self.assertEqual(paper.load_state(case.nightly.root).pending[0]['sent']['qty'], 5)
        self.assertEqual(case.store.snapshot()['next_stage'], 'OUTCOME_COMMITTED')
        self.assertEqual(case.cas._control()['groups'][-1]['status'], 'COMPLETE')
        case.reopen(result['head'])
        before = self.retained(case)
        self.assertEqual(case.stage._run('SUBMISSION_CAPTURED', case.submission), result)
        self.assertEqual(case.stage._prepare(case.registry, case.packet), case.prepared)
        self.assertEqual(self.retained(case), before)
        self.assertEqual(case.inventory(), case.before)
