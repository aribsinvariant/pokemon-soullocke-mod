"""Run actual ARM functions in mGBA; opt in with SOUL_ROM, SOUL_ELF, SOUL_ADAPTER."""
import ctypes as C
import os
from pathlib import Path
import subprocess
import unittest


@unittest.skipUnless(os.environ.get('SOUL_ADAPTER'), 'set SOUL_ADAPTER, SOUL_ROM and SOUL_ELF for mGBA tests')
class RomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = C.CDLL(os.environ['SOUL_ADAPTER'])
        cls.lib.sl_new.argtypes = [C.c_char_p]; cls.lib.sl_new.restype = C.c_void_p
        cls.lib.sl_run.argtypes = [C.c_void_p,C.c_uint,C.c_uint]
        cls.lib.sl_read.argtypes = [C.c_void_p,C.c_uint,C.c_uint]; cls.lib.sl_read.restype = C.c_uint
        cls.lib.sl_write.argtypes = [C.c_void_p,C.c_uint,C.c_uint,C.c_uint]
        cls.lib.sl_call.argtypes = [C.c_void_p,C.c_uint,C.POINTER(C.c_uint),C.c_uint]; cls.lib.sl_call.restype = C.c_uint
        cls.lib.sl_free.argtypes = [C.c_void_p]
        symbols = subprocess.check_output([os.environ.get('ARM_NM','arm-none-eabi-nm'), os.environ['SOUL_ELF']], text=True)
        cls.symbols = {s[2]:int(s[0],16) for line in symbols.splitlines() if len(s:=line.split())==3}
        # Values are append-only in pokemon.h. Resolve the enum from source, not hardcoded guesses.
        header = (Path(__file__).parents[2]/'include/pokemon.h').read_text()
        labels = header.split('enum {',1)[1].split('};',1)[0]
        cls.fields = {label.strip():i for i,label in enumerate(labels.split(',')) if label.strip()}

    def setUp(self):
        self.h = self.lib.sl_new(os.environ['SOUL_ROM'].encode())
        self.assertTrue(self.h)
        self.lib.sl_run(self.h, 120, 0)
        for pointer, block in [('gSaveBlock1Ptr','gSaveblock1'),('gSaveBlock2Ptr','gSaveblock2'),('gPokemonStoragePtr','gPokemonStorage')]:
            self.write(self.symbols[pointer],self.symbols[block])
        self.call('NewGameInitData')
        self.call('SoulLink_Frame')
        self.box = self.symbols['gSoulLinkMailbox']
        self.storage = self.read(self.symbols['gPokemonStoragePtr'])
        self.save = self.storage + 0x83d0
        self.party = self.symbols['gPlayerParty']
        self.write(self.box+20,2)
        self.write(self.box+40,1)
        self.write(self.box+24,123)
        self.call('SoulLink_Frame')

    def tearDown(self):
        self.lib.sl_free(self.h)

    def call(self,name,*args):
        return self.lib.sl_call(self.h,self.symbols[name],(C.c_uint*len(args))(*args),len(args))

    def read(self,address,width=4): return self.lib.sl_read(self.h,address,width)
    def write(self,address,value,width=4): self.lib.sl_write(self.h,address,value,width)

    def mon(self, species=1):
        self.call('CreateMon', self.party,species,5,32,0,0,0,0)
        self.call('SoulLink_Starter')
        self.call('SoulLink_Receive',self.party)
        return self.call('GetMonData3',self.party,self.fields['MON_DATA_SOUL_ID'],0)

    def test_battle_item_rule_keeps_balls_and_field_items(self):
        potion, ball, x_attack = 13, 4, 75
        self.write(self.box + 32, 1 << 12)
        self.call('SoulLink_Frame')
        for item in (potion, x_attack):
            self.assertEqual(self.call('GetItemBattleUsage', item), 0)
            self.assertEqual(self.call('GetItemBattleFunc', item), 0)
        self.assertNotEqual(self.call('GetItemBattleUsage', ball), 0)
        self.assertNotEqual(self.call('GetItemBattleFunc', ball), 0)
        self.assertNotEqual(self.call('GetItemFieldFunc', potion), 0)
        self.write(self.box + 32, 0)
        self.call('SoulLink_Frame')
        self.assertNotEqual(self.call('GetItemBattleFunc', potion), 0)

    def test_force_set_overrides_options_only_when_enabled(self):
        self.call('AllocateBattleResources')
        options = self.read(self.symbols['gSaveBlock2Ptr']) + 0x14
        self.write(options, 0, 2)  # Player selected Shift.
        for rules, expected in ((1 << 13, 1), (0, 0)):
            self.write(self.box + 32, rules)
            self.call('SoulLink_Frame')
            self.call('BattleStartClearSetData')
            self.assertEqual(self.read(self.symbols['gBattleScripting'] + 0x1d, 1), expected)
        self.call('FreeBattleResources')

    def test_start_options_and_continue_preserves_preferences(self):
        options = self.read(self.symbols['gSaveBlock2Ptr']) + 0x14
        self.assertEqual(self.read(options, 2) & 0x6ff, 2 | (1 << 9) | (1 << 10))
        self.write(self.save + 4, 0)  # First room configuration, even if already locked.
        self.write(self.box + 32, (1 << 23) | (1 << 14) | (19 << 18))
        self.call('SoulLink_Frame')
        self.assertEqual(self.read(options, 2) & 0x6ff, 1 | (19 << 3))
        self.write(options, 2 | (3 << 3), 2)
        self.call('SoulLink_Frame')
        self.assertEqual(self.read(options, 2), 2 | (3 << 3))

    def test_mailbox_and_save_layout(self):
        self.assertEqual(self.read(self.box),0x534F554C)
        self.assertEqual(self.read(self.box+8),0x534C0001)
        self.assertEqual(self.read(self.save),0x534F554C)
        self.assertEqual(self.read(self.save+4),123)

    def test_pending_cannot_battle_then_death_cannot_be_healed(self):
        self.assertEqual(self.mon(),512)
        hp = self.fields['MON_DATA_HP']
        self.assertEqual(self.call('GetMonData3',self.party,hp,0),0)
        self.write(self.save+20+511,2,1)
        self.write(self.box+160+511*18+17,1,1)
        self.assertGreater(self.call('GetMonData3',self.party,hp,0),0)
        self.call('SoulLink_Faint', self.party)
        self.assertEqual(self.read(self.save+20+511,1),3)
        scratch=0x0203ffe0
        self.write(scratch,99,2)
        self.call('SetMonData',self.party,hp,scratch)
        self.assertEqual(self.call('GetMonData3',self.party,hp,0),0)
        self.assertEqual(self.read(self.party+86,2),0)
        self.assertEqual(self.call('PokemonUseItemEffects',self.party,24,0,0,0),1) # Revive has no effect.
        seq=self.read(self.save+16)
        self.call('SoulLink_Faint',self.party)
        self.assertEqual(self.read(self.save+16),seq)

    def test_evolution_and_storage_conversion_preserve_id(self):
        self.mon()
        scratch=0x0203ffe0
        self.write(scratch,2,2)
        self.call('SetMonData',self.party,self.fields['MON_DATA_SPECIES'],scratch)
        self.assertEqual(self.call('GetMonData3',self.party,self.fields['MON_DATA_SOUL_ID'],0),512)
        self.call('BoxMonToMon',self.party,self.party+100)
        self.assertEqual(self.call('GetMonData3',self.party+100,self.fields['MON_DATA_SOUL_ID'],0),512)

    def test_link_revives_pending_zero_hp_only_at_safe_overworld(self):
        self.mon()
        self.write(self.party+86,0,2)  # A game routine persisted the masked pending HP.
        self.write(self.box+160+511*18+16,2,1)
        self.write(self.box+160+511*18+17,1,1)
        self.write(self.box+116,10)
        self.call('ScriptContext_Init')
        self.call('LockPlayerFieldControls')
        self.call('SoulLink_Overworld')
        self.assertEqual(self.read(self.party+86,2),0)
        self.call('UnlockPlayerFieldControls')
        self.call('SoulLink_Overworld')
        self.assertEqual(self.read(self.save+20+511,1),2)
        self.assertGreater(self.read(self.party+86,2),0)
        self.assertEqual(self.call('GetMonData3',self.party,self.fields['MON_DATA_HP'],0),
                         self.call('GetMonData3',self.party,self.fields['MON_DATA_MAX_HP'],0))

    def test_link_snapshot_preserves_damage_and_never_revives_deaths(self):
        self.mon()
        self.call('ScriptContext_Init')
        self.call('UnlockPlayerFieldControls')
        # Local state, remote state, stored HP, ended run, expected HP.
        for version,(local,remote,hp,ended,expected) in enumerate(
                [(1,2,3,0,3),(2,2,0,0,0),(3,2,0,0,0),(1,3,0,0,0),(1,2,0,1,0)],10):
            with self.subTest(local=local,remote=remote,hp=hp,ended=ended):
                self.write(self.save+20+511,local,1)
                self.write(self.party+86,hp,2)
                self.write(self.box+160+511*18+16,remote,1)
                self.write(self.box+160+511*18+17,1,1)
                self.write(self.box+116,version)
                self.write(self.save+584,0,1)
                self.write(self.box+48,ended)
                self.call('SoulLink_Overworld')
                self.assertEqual(self.read(self.party+86,2),expected)

    def linked_party_mon(self, slot, soul_id, species=1):
        address = self.party + slot * 100
        self.call('CreateMon',address,species,5,32,0,0,0,0)
        scratch = 0x0203ffe0
        self.write(scratch,soul_id,2)
        self.call('SetMonData',address,self.fields['MON_DATA_SOUL_ID'],scratch)
        self.write(self.save+20+soul_id-1,2,1)
        self.write(self.box+160+(soul_id-1)*18+17,1,1)
        self.write(self.symbols['gPlayerPartyCount'],slot+1,1)

    def party_ids(self):
        return [self.call('GetMonData3',self.party+i*100,self.fields['MON_DATA_SOUL_ID'],0)
                for i in range(self.read(self.symbols['gPlayerPartyCount'],1))]

    def test_catch_preserves_lead_and_existing_party_order(self):
        for rule in (32,16):  # Paired party and team type rules both reconcile membership.
            with self.subTest(rule=rule):
                self.call('ZeroPlayerPartyMons')
                for soul_id in (20,5):
                    self.write(self.box+160+(soul_id-1)*18+17,0,1)
                self.write(self.save+12,rule)
                self.linked_party_mon(0,512)
                self.call('ScriptContext_Init')
                self.call('UnlockPlayerFieldControls')
                self.call('SoulLink_Overworld')
                self.linked_party_mon(1,20)
                self.call('SoulLink_Overworld')
                self.assertEqual(self.party_ids(),[512,20])
                # A player-selected lead and the rest of the order survive the next catch.
                self.linked_party_mon(0,20)
                self.linked_party_mon(1,512)
                self.linked_party_mon(2,5)
                self.call('SoulLink_Overworld')
                self.assertEqual(self.party_ids(),[20,512,5])

    def test_party_change_keeps_survivor_order_and_appends_withdrawals(self):
        self.write(self.save+12,32)
        for slot,soul_id in enumerate((20,512,5)):
            self.linked_party_mon(slot,soul_id)
        self.call('ScriptContext_Init')
        self.call('UnlockPlayerFieldControls')
        self.call('SoulLink_Overworld')
        # Move pair 5 to the PC and request it back alongside the surviving starter.
        self.call('SetBoxMonAt',0,0,self.party+200)
        self.call('ZeroMonData',self.party+200)
        self.write(self.symbols['gPlayerPartyCount'],2,1)
        self.write(self.box+160+(20-1)*18+17,0,1)
        self.call('SoulLink_Overworld')
        self.assertEqual(self.party_ids(),[512,5])
        self.assertEqual(self.call('GetBoxMonDataAt',0,0,self.fields['MON_DATA_SOUL_ID']),20)

    def test_remote_death_waits_for_safe_overworld(self):
        self.mon()
        self.write(self.save+20+511,2,1)
        self.write(self.box+160+511*18+17,1,1)
        self.write(self.box+160+511*18+16,3,1)
        self.write(self.box+116,10)
        self.call('SoulLink_Frame')
        self.assertEqual(self.read(self.save+20+511,1),2)
        self.call('ScriptContext_Init')
        self.call('LockPlayerFieldControls')
        self.call('SoulLink_Overworld')
        self.assertEqual(self.read(self.save+20+511,1),2)
        self.call('UnlockPlayerFieldControls')
        self.call('SoulLink_Overworld')
        self.assertEqual(self.read(self.save+20+511,1),3)
        self.assertEqual(self.call('GetMonData3',self.party,self.fields['MON_DATA_HP'],0),0)

    def test_ordinary_reload_replays_a_recorded_death(self):
        self.mon()
        self.write(self.save+20+511,2,1)
        old_seq=self.read(self.save+16)
        self.write(self.box+124,old_seq+2)
        self.write(self.box+160+511*18+16,3,1)
        self.write(self.box+116,10)
        self.call('SoulLink_Frame')
        self.assertEqual(self.read(self.save+16),old_seq+2)
        self.assertNotEqual(self.read(self.box+20),3)
        self.call('ScriptContext_Init');self.call('UnlockPlayerFieldControls')
        self.call('SoulLink_Overworld')
        self.assertEqual(self.read(self.save+20+511,1),3)

    def test_boxed_field_move_uses_surrogate_without_changing_party(self):
        self.mon()
        # Teach Surf (57), put the mon in box zero, and empty the party.
        scratch=0x0203ffe0
        self.write(scratch,57,2)
        self.call('SetMonData',self.party,self.fields['MON_DATA_MOVE1'],scratch)
        self.call('SetBoxMonAt',0,0,self.party)
        self.call('ZeroPlayerPartyMons')
        self.assertEqual(self.call('SoulLink_FindFieldMove',57),7)
        self.assertEqual(self.call('GetMonData3',self.party,self.fields['MON_DATA_SPECIES'],0),0)

    def test_randomizer_is_stable_and_player_specific(self):
        self.write(self.save+12,256|512|2048)
        self.write(self.save+8,12345)
        first=[self.call('SoulLink_RandomSpecies',1,key,0) for key in range(8)]
        self.assertEqual(first,[self.call('SoulLink_RandomSpecies',1,key,0) for key in range(8)])
        self.write(self.save+585,1,1) # SoulSave.player
        second=[self.call('SoulLink_RandomSpecies',1,key,0) for key in range(8)]
        self.assertNotEqual(first,second)
        self.assertTrue(all(1<=s<=411 and not 252<=s<=276 for s in first+second))


if __name__=='__main__': unittest.main()
