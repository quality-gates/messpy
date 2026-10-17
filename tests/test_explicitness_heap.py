from collections import Counter
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from messpy.cli import run


CASES = [('list_siblings_quiet',
  'def probe(shared):\n    pair = [shared, []]\n    pair[1].append(97)\n',
  'probe',
  [],
  []),
 ('dict_siblings_quiet',
  "def probe(shared):\n    pair = {'left': shared, 'right': []}\n    pair['right'].append(97)\n",
  'probe',
  [],
  []),
 ('literal_list_shared',
  'def probe(shared):\n    pair = [shared, []]\n    pair[0].append(97)\n',
  'probe',
  [('ImplicitOutput', 3)],
  [97]),
 ('direct_alias_replace_private',
  'def probe(shared):\n'
  '    pair = [shared]\n'
  '    alias = pair\n'
  '    alias[0] = []\n'
  '    pair[0].append(97)\n',
  'probe',
  [],
  []),
 ('direct_alias_insert_shared',
  'def probe(shared):\n'
  '    pair = [[]]\n'
  '    alias = pair\n'
  '    alias[0] = shared\n'
  '    pair[0].append(97)\n',
  'probe',
  [('ImplicitOutput', 5)],
  [97]),
 ('nested_list_insert_shared',
  'def probe(shared):\n'
  '    child = [[]]\n'
  '    parent = [child]\n'
  '    child[0] = shared\n'
  '    parent[0][0].append(97)\n',
  'probe',
  [('ImplicitOutput', 5)],
  [97]),
 ('nested_list_replace_private',
  'def probe(shared):\n'
  '    child = [shared]\n'
  '    parent = [child]\n'
  '    child[0] = []\n'
  '    parent[0][0].append(97)\n',
  'probe',
  [],
  []),
 ('nested_dict_insert_shared',
  'def probe(shared):\n'
  "    child = {'leaf': []}\n"
  "    parent = {'child': child}\n"
  "    child['leaf'] = shared\n"
  "    parent['child']['leaf'].append(97)\n",
  'probe',
  [('ImplicitOutput', 5)],
  [97]),
 ('nested_dict_replace_private',
  'def probe(shared):\n'
  "    child = {'leaf': shared}\n"
  "    parent = {'child': child}\n"
  "    child['leaf'] = []\n"
  "    parent['child']['leaf'].append(97)\n",
  'probe',
  [],
  []),
 ('selected_alias_insert_shared',
  'def probe(shared):\n'
  '    parent = [[[]]]\n'
  '    selected = parent[0]\n'
  '    selected[0] = shared\n'
  '    parent[0][0].append(97)\n',
  'probe',
  [('ImplicitOutput', 5)],
  [97]),
 ('selected_alias_replace_private',
  'def probe(shared):\n'
  '    parent = [[shared]]\n'
  '    selected = parent[0]\n'
  '    selected[0] = []\n'
  '    parent[0][0].append(97)\n',
  'probe',
  [],
  []),
 ('nested_append_shared',
  'def probe(shared):\n'
  '    child = []\n'
  '    parent = [child]\n'
  '    child.append(shared)\n'
  '    parent[0][0].append(97)\n',
  'probe',
  [('ImplicitOutput', 5)],
  [97]),
 ('branch_alias_insert_shared',
  'def probe(shared, choose=True):\n'
  '    pair = [[]]\n'
  '    alias = pair\n'
  '    if choose:\n'
  '        marker = 1\n'
  '    alias[0] = shared\n'
  '    pair[0].append(97)\n',
  'probe',
  [('ImplicitOutput', 7)],
  [97]),
 ('branch_alias_replace_private',
  'def probe(shared, choose=True):\n'
  '    pair = [shared]\n'
  '    alias = pair\n'
  '    if choose:\n'
  '        marker = 1\n'
  '    alias[0] = []\n'
  '    pair[0].append(97)\n',
  'probe',
  [],
  []),
 ('copied_literal_private_sibling',
  'def probe(shared):\n    copied = list([[], shared])\n    copied[0].append(97)\n',
  'probe',
  [],
  []),
 ('copy_private_outer_append',
  'def probe(shared):\n    copied = list(shared)\n    copied.append(97)\n',
  'probe',
  [],
  []),
 ('helper_private_outer_append',
  'def grow(items):\n'
  '    items.append(97)\n'
  'def probe(shared):\n'
  '    holder = [shared]\n'
  '    grow(holder)\n',
  'probe',
  [],
  []),
 ('helper_private_sibling_append',
  'def grow(items):\n'
  '    items[1].append(97)\n'
  'def probe(shared):\n'
  '    holder = [shared, []]\n'
  '    grow(holder)\n',
  'probe',
  [],
  []),
 ('helper_shared_sibling_append',
  'def grow(items):\n'
  '    items[0].append(97)\n'
  'def probe(shared):\n'
  '    holder = [shared, []]\n'
  '    grow(holder)\n',
  'probe',
  [('ImplicitOutput', 5)],
  [97]),
 ('nonlinking_literal_helper',
  'def inspect(holder, other):\n'
  '    return 1\n'
  'def probe(shared):\n'
  '    holder = [[]]\n'
  '    inspect(holder, shared)\n'
  '    holder[0].append(97)\n',
  'probe',
  [],
  []),
 ('nonlinking_builtin_reader',
  'def inspect(holder, other):\n'
  '    return len(other)\n'
  'def probe(shared):\n'
  '    holder = [[]]\n'
  '    inspect(holder, shared)\n'
  '    holder[0].append(97)\n',
  'probe',
  [],
  []),
 ('nonlinking_samefile_reader',
  'def size(other):\n'
  '    return len(other)\n'
  'def inspect(holder, other):\n'
  '    return size(other)\n'
  'def probe(shared):\n'
  '    holder = [[]]\n'
  '    inspect(holder, shared)\n'
  '    holder[0].append(97)\n',
  'probe',
  [],
  []),
 ('helper_replace_shared_with_private',
  'def reset(holder):\n'
  '    holder[0] = []\n'
  'def probe(shared):\n'
  '    holder = [shared]\n'
  '    reset(holder)\n'
  '    holder[0].append(97)\n',
  'probe',
  [],
  []),
 ('helper_insert_shared',
  'def put(holder, value):\n'
  '    holder[0] = value\n'
  'def probe(shared):\n'
  '    holder = [[]]\n'
  '    put(holder, shared)\n'
  '    holder[0].append(97)\n',
  'probe',
  [('ImplicitOutput', 6)],
  [97]),
 ('callback_holder_insertion',
  'def run(callback):\n'
  '    callback()\n'
  'def probe(shared):\n'
  '    holder = [[]]\n'
  '    def put():\n'
  '        holder[0] = shared\n'
  '    run(put)\n'
  '    holder[0].append(97)\n',
  'probe',
  [('ImplicitOutput', 8)],
  [97]),
 ('uncalled_closure_rebinding',
  'def probe(shared):\n'
  '    private = []\n'
  '    def unused():\n'
  '        nonlocal private\n'
  '        private = shared\n'
  '    private.append(97)\n',
  'probe',
  [],
  []),
 ('returned_alias_then_append',
  'def identity(value):\n'
  '    return value\n'
  'def probe(shared):\n'
  '    alias = identity(shared)\n'
  '    alias.append(97)\n',
  'probe',
  [('ImplicitOutput', 5)],
  [97]),
 ('returned_alias_immediate_append',
  'def identity(value):\n    return value\ndef probe(shared):\n    identity(shared).append(97)\n',
  'probe',
  [('ImplicitOutput', 4)],
  [97]),
 ('returned_private_holder_sibling',
  'def wrap(value):\n'
  '    return [value, []]\n'
  'def probe(shared):\n'
  '    holder = wrap(shared)\n'
  '    holder[1].append(97)\n',
  'probe',
  [],
  []),
 ('dict_read_method_private_sibling',
  'def probe(shared):\n'
  "    holder = {'shared': shared, 'private': []}\n"
  "    holder.get('private').append(97)\n",
  'probe',
  [],
  []),
 ('parameter_receiver_alias',
  'def probe(receiver):\n    alias = receiver\n    alias.items.append(97)\n',
  'probe',
  [('ImplicitOutput', 3)],
  [97]),
 ('parameter_receiver_in_holder',
  'def probe(receiver):\n    holder = [receiver]\n    holder[0].items.append(97)\n',
  'probe',
  [('ImplicitOutput', 3)],
  [97]),
 ('parameter_field_alias_rebind_private',
  'def probe(receiver):\n    alias = receiver.items\n    alias = []\n    alias.append(97)\n',
  'probe',
  [],
  []),
 ('instance_receiver_alias',
  'class Box:\n    def probe(self):\n        alias = self\n        alias.items.append(97)\n',
  'Box.probe',
  [('ImplicitOutput', 4)],
  [97]),
 ('instance_receiver_alias_in_holder',
  'class Box:\n'
  '    def probe(self):\n'
  '        alias = self\n'
  '        holder = [alias]\n'
  '        holder[0].items.append(97)\n',
  'Box.probe',
  [('ImplicitOutput', 5)],
  [97]),
 ('instance_receiver_alias_rebind_private',
  'class Box:\n'
  '    def probe(self):\n'
  '        alias = self\n'
  '        alias = []\n'
  '        alias.append(97)\n',
  'Box.probe',
  [],
  []),
 ('plain_record_private_sibling',
  'class Holder:\n'
  '    pass\n'
  'def probe(shared):\n'
  '    record = Holder()\n'
  '    record.left = shared\n'
  '    record.right = []\n'
  '    record.right.append(97)\n',
  'probe',
  [],
  []),
 ('plain_record_shared_sibling',
  'class Holder:\n'
  '    pass\n'
  'def probe(shared):\n'
  '    record = Holder()\n'
  '    record.left = shared\n'
  '    record.right = []\n'
  '    record.left.append(97)\n',
  'probe',
  [('ImplicitOutput', 7)],
  [97]),
 ('plain_record_replace_private',
  'class Holder:\n'
  '    pass\n'
  'def probe(shared):\n'
  '    record = Holder()\n'
  '    record.left = shared\n'
  '    record.left = []\n'
  '    record.left.append(97)\n',
  'probe',
  [],
  []),
 ('plain_record_helper_nonlinking',
  'class Holder:\n'
  '    pass\n'
  'def inspect(record, other):\n'
  '    return len(other)\n'
  'def probe(shared):\n'
  '    record = Holder()\n'
  '    record.items = []\n'
  '    inspect(record, shared)\n'
  '    record.items.append(97)\n',
  'probe',
  [],
  [])]


class HeapOwnershipTests(unittest.TestCase):
    def test_deep_call_expansion_retains_uncertainty(self):
        source = '''def stage0(holder, shared):
    stage1(holder, shared)
def stage1(holder, shared):
    stage2(holder, shared)
def stage2(holder, shared):
    stage3(holder, shared)
def stage3(holder, shared):
    stage4(holder, shared)
def stage4(holder, shared):
    stage5(holder, shared)
def stage5(holder, shared):
    stage6(holder, shared)
def stage6(holder, shared):
    stage7(holder, shared)
def stage7(holder, shared):
    stage8(holder, shared)
def stage8(holder, shared):
    stage9(holder, shared)
def stage9(holder, shared):
    holder[0] = shared
def probe(shared):
    holder = [[]]
    stage0(holder, shared)
    holder[0].append(97)
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'deep.py'
            path.write_text(source)
            out, err = StringIO(), StringIO()
            status = run([str(path), 'json', 'explicitness', '--strict'], out, err)
            report = json.loads(out.getvalue())
            self.assertEqual(2, status)
            self.assertEqual('', err.getvalue())
            self.assertEqual([], report['errors'])
            actual = [(item['ruleName'], item['line']) for item in report['findings'] if item['context'] == 'probe']
            self.assertEqual([('UnknownEffect', 24)], actual)
        namespace = {}
        exec(compile(source, 'deep', 'exec'), namespace)
        shared = []
        namespace['probe'](shared)
        self.assertEqual([97], shared)

    def test_caller_mutations_and_private_twins(self):
        for name, source, focus, expected, mutation in CASES:
            with self.subTest(case=name):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / 'probe.py'
                    path.write_text(source)
                    out, err = StringIO(), StringIO()
                    status = run([str(path), 'json', 'explicitness', '--strict'], out, err)
                    report = json.loads(out.getvalue())
                    self.assertEqual('', err.getvalue())
                    self.assertEqual([], report['errors'])
                    self.assertEqual(2 if report['findings'] else 0, status)
                    actual = Counter((item['ruleName'], item['line']) for item in report['findings']
                                     if item['context'] == focus)
                    self.assertEqual(Counter(expected), actual)
                    for item in report['findings']:
                        self.assertFalse(item['suppressed'])
                        self.assertTrue(item['message'])
                        self.assertEqual(path.resolve(), Path(item['path']).resolve())
                namespace = {}
                exec(compile(source, name, 'exec'), namespace)
                shared = []
                if name.startswith(('parameter_', 'instance_')):
                    receiver = SimpleNamespace(items=shared)
                    function = namespace['Box'].probe if focus == 'Box.probe' else namespace['probe']
                    function(receiver)
                else:
                    namespace['probe'](shared)
                self.assertEqual(mutation, shared)
