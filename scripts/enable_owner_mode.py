r"""Owner's standing order (2026-10-04): add the 'owner' autonomy mode. Run it yourself:

    .venv\Scripts\python.exe scripts\enable_owner_mode.py

In owner mode Chutku runs every step without asking EXCEPT: changing files (write, move, copy, organize, undo),
any deletion (Recycle Bin, permanent delete, forgetting memory/routines), power / killing programs / network off,
messages to people not in your memory, and steps that follow text read from web pages or messages.
Everything is still logged; Stop still works; protected system folders are still refused.
Applies once (it fails with an AssertionError if already applied). Then tell Claude to finish the UI and tests.
"""
from pathlib import Path
import os
os.chdir(r"D:\Project\Chutku")

p = Path("chutku/policy/kernel.py"); s = p.read_text(encoding="utf-8")
old = '''    AUTO_EDITS = "auto_edits"  # also journaled/compensatable data changes (<= R2)
'''
assert old in s
s = s.replace(old, old + '''    OWNER = "owner"            # the owner's standing order: everything runs, except changing or deleting files,
                               # deletions of any kind, power/kill/network-off (R4) and messages to unknown people
''')
old = '''            AutonomyMode.AUTO_EDITS: Risk.DATA_MODIFICATION}'''
assert old in s
s = s.replace(old, '''            AutonomyMode.AUTO_EDITS: Risk.DATA_MODIFICATION, AutonomyMode.OWNER: Risk.EXTERNAL_SIDE_EFFECT}''')
old = '''AUTO_EDIT_REVERSIBILITY = frozenset({"journaled", "compensatable", "single_use", "transient"})'''
assert old in s
s = s.replace(old, old + '''
# File tools that only ever create something new (they never change or remove an existing file).
CREATE_ONLY_TOOLS = frozenset({"filesystem.create_directory", "files.zip", "files.unzip", "code.build_project",
                               "screen.capture"})''')
old = '''protected_reason=None, exposed=None) -> Authorization:'''
assert s.count(old) == 1
s = s.replace(old, '''protected_reason=None, exposed=None, owner_question=None) -> Authorization:''')
old = '''            return self._delegated(tool, risk, confirmed_on_screen, autonomy, tainted,
                                   tainted if exposed is None else exposed)'''
assert old in s
s = s.replace(old, '''            return self._delegated(tool, risk, confirmed_on_screen, autonomy, tainted,
                                   tainted if exposed is None else exposed, owner_question)''')
old = '''    def _delegated(tool: Tool, risk: Risk, confirmed_on_screen: bool, autonomy, tainted, exposed) -> Authorization:'''
assert old in s
s = s.replace(old, '''    def _delegated(tool: Tool, risk: Risk, confirmed_on_screen: bool, autonomy, tainted, exposed,
                   owner_question=None) -> Authorization:''')
old = '''        if tool.deletes:
            return Authorization(Decision.CONFIRM, risk, "Deleting always asks first.")
        ceiling = _CEILING[mode]'''
assert old in s
s = s.replace(old, '''        if tool.deletes:
            return Authorization(Decision.CONFIRM, risk, "Deleting always asks first.")
        if mode == AutonomyMode.OWNER:
            return PolicyKernel._owner(tool, risk, tainted, exposed, owner_question)
        ceiling = _CEILING[mode]''')
s = s.rstrip("\n") + '''

    @staticmethod
    def _owner(tool: Tool, risk: Risk, tainted, exposed, owner_question) -> Authorization:
        """The owner's standing order (2026-10-04): do everything without asking, except file changes and deletions."""
        if risk >= Risk.DESTRUCTIVE_OR_PRIVILEGED:
            return Authorization(Decision.CONFIRM, risk, "Power, killing a program or turning the network off can lose "
                                 "unsaved work; this asks first.")
        if tool.resource_access == "modify" and tool.name not in CREATE_ONLY_TOOLS:
            return Authorization(Decision.CONFIRM, risk, "Changing files always asks first.")
        if owner_question:
            return Authorization(Decision.CONFIRM, risk, str(owner_question))
        if tainted and risk >= Risk.DATA_MODIFICATION:
            # Text read from a web page or a message must not be able to make Chutku act on its own.
            return Authorization(Decision.CONFIRM, risk, "This step follows content read from outside; confirm it.")
        if exposed and tool.network_egress:
            return Authorization(Decision.CONFIRM, risk, "A network request after reading untrusted content needs on-screen confirmation.")
        return Authorization(Decision.ALLOW, risk, "Allowed automatically by your standing order (owner mode).")
'''
p.write_text(s, encoding="utf-8")

p = Path("chutku/runtime.py"); s = p.read_text(encoding="utf-8")
old = '''                                     protected_reason=self.protected_target(tool, arguments))'''
assert s.count(old) == 1
s = s.replace(old, '''                                     protected_reason=self.protected_target(tool, arguments),
                                     owner_question=self.owner_question(tool, arguments) if autonomy == "owner" else None)

    def owner_question(self, tool, arguments):
        """In owner mode a message to someone Chutku does not know yet still asks; once they are remembered,
        messages to them go straight out."""
        if tool.name != "message.send":
            return None
        from chutku.tools.apps_extra import known_recipient
        to = str(arguments.get("to", ""))
        if known_recipient(to, self.memory):
            return None
        return (f"{to} is not in your memory yet, so this message asks first. Say 'remember {to} is my ...' "
                "and later messages to them go straight out.")''')
p.write_text(s, encoding="utf-8")

p = Path("chutku/tools/apps_extra.py"); s = p.read_text(encoding="utf-8")
old = "def recipient(to):"
assert s.count(old) == 1
s = s.replace(old, '''def known_recipient(to, memory):
    """The owner's memory names this person (a nickname, relation, chat name, or a saved contact number)."""
    if recipient(to) is not None:
        return True
    if _digits(to):
        return False  # a raw number nobody saved is someone new
    try:
        resolve_contact(to, memory, use_mind=False)
        return True
    except ValueError:
        return False


def recipient(to):''')
p.write_text(s, encoding="utf-8")

p = Path("chutku/core/preferences.py"); s = p.read_text(encoding="utf-8")
s = s.replace('_MODES = {"review", "auto_safe", "auto_edits"}', '_MODES = {"review", "auto_safe", "auto_edits", "owner"}')
s = s.replace('"handsfree_mode must be review, auto_safe or auto_edits."', '"handsfree_mode must be review, auto_safe, auto_edits or owner."')
p.write_text(s, encoding="utf-8")
p = Path("chutku/dashboard.py"); s = p.read_text(encoding="utf-8")
s = s.replace('"Choose review, auto_safe or auto_edits."', '"Choose review, auto_safe, auto_edits or owner."')
p.write_text(s, encoding="utf-8")
print("ok")
