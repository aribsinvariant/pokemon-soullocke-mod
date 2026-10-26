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
        cls.lib.sl_cycles.argtypes = [C.c_void_p]; cls.lib.sl_cycles.restype = C.c_uint64
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

    def test_partner_species_lookup(self):
        for soul_id in (20, 512):
            self.linked_party_mon(0, soul_id)
            remote = self.box + 160 + (soul_id - 1) * 18
            self.assertEqual(self.call('SoulLink_GetPartnerSpecies', self.party), 0)
            self.write(remote + 12, 25, 2)
            self.assertEqual(self.call('SoulLink_GetPartnerSpecies', self.party), 25)
            self.write(self.box + 20, 0)  # Cached identity survives disconnection.
            self.write(self.save + 20 + soul_id - 1, 3, 1)
            self.assertEqual(self.call('SoulLink_GetPartnerSpecies', self.party), 25)
            self.set_mon_field('MON_DATA_IS_EGG', 1)
            self.assertEqual(self.call('SoulLink_GetPartnerSpecies', self.party), 0)
            self.set_mon_field('MON_DATA_IS_EGG', 0)
            for state in (0, 1, 4):
                self.write(self.save + 20 + soul_id - 1, state, 1)
                self.assertEqual(self.call('SoulLink_GetPartnerSpecies', self.party), 0)
            self.write(self.save + 20 + soul_id - 1, 2, 1)
            for species in (0, 412, 65535):
                self.write(remote + 12, species, 2)
                self.assertEqual(self.call('SoulLink_GetPartnerSpecies', self.party), 0)
            self.write(remote + 12, 25, 2)
            for invalid_id in (0, 513, 65535):
                self.set_mon_field('MON_DATA_SOUL_ID', invalid_id)
                self.assertEqual(self.call('SoulLink_GetPartnerSpecies', self.party), 0)
        self.set_mon_field('MON_DATA_SOUL_ID', 512)
        self.write(self.save, 0)
        self.assertEqual(self.call('SoulLink_GetPartnerSpecies', self.party), 0)

    def test_partner_icon_resources_and_refresh(self):
        self.call('ResetSpriteData')
        self.call('FreeAllSpritePalettes')
        # Two icons share an owned palette; removing one must not release it.
        first = self.call('SoulPartnerIcon_Update', 255, 25)
        second = self.call('SoulPartnerIcon_Update', 255, 25)
        self.assertLess(first, 64)
        self.assertLess(second, 64)
        palette_tag = 0xf210 + self.call('GetValidMonIconPalIndex', 25)
        palette = self.call('IndexOfSpritePaletteTag', palette_tag)
        self.assertLess(palette, 16)
        self.assertEqual(self.call('SoulPartnerIcon_Update', first, 25), first)
        self.call('SoulPartnerIcon_Destroy', first)
        self.assertEqual(self.call('IndexOfSpritePaletteTag', palette_tag), palette)
        self.call('SoulPartnerIcon_Destroy', second)
        self.assertEqual(self.call('IndexOfSpritePaletteTag', palette_tag), 255)
        # Repeated replacements release tiles and palettes, including removal.
        icon = 255
        for _ in range(80):
            for species in (1, 4, 7, 25):
                icon = self.call('SoulPartnerIcon_Update', icon, species)
                self.assertLess(icon, 64)
        self.assertEqual(self.call('SoulPartnerIcon_Update', icon, 0), 255)
        # Saturating palettes must fail safely and permit a later retry.
        for i in range(16):
            self.call('AllocSpritePalette', 0xe000 + i)
        self.assertEqual(self.call('SoulPartnerIcon_Update', 255, 25), 255)
        self.call('FreeAllSpritePalettes')
        icon = self.call('SoulPartnerIcon_Update', 255, 25)
        self.assertLess(icon, 64)
        self.call('SoulPartnerIcon_Destroy', icon)
        # Existing party icon palettes are borrowed and must not be freed.
        self.call('LoadMonIconPalette', 25)
        tag = 56000 + self.call('GetValidMonIconPalIndex', 25)
        palette = self.call('IndexOfSpritePaletteTag', tag)
        self.assertLess(palette, 16)
        icon = self.call('SoulPartnerIcon_Update', 255, 25)
        self.call('SoulPartnerIcon_Destroy', icon)
        self.assertEqual(self.call('IndexOfSpritePaletteTag', tag), palette)

    def test_partner_healthbox_switch_visibility_and_doubles(self):
        self.call('ResetSpriteData')
        self.call('FreeAllSpritePalettes')
        self.write(self.symbols['gBattleTypeFlags'], 1)  # Doubles.
        for battler in range(4):
            self.write(self.symbols['gBattlerPositions'] + battler, battler, 1)
        self.call('BattleLoadAllHealthBoxesGfxAtOnce')
        for slot, species in enumerate((25, 133)):
            self.linked_party_mon(slot, slot + 1)
            self.write(self.box + 160 + slot * 18 + 12, species, 2)
        healthboxes = []
        for battler, slot in ((0, 0), (2, 1), (1, 0)):
            self.write(self.symbols['gBattlerPartyIndexes'] + battler * 2, slot, 2)
            healthbox = self.call('CreateBattlerHealthboxSprites', battler)
            self.write(self.symbols['gHealthboxSpriteIds'] + battler, healthbox, 1)
            self.call('InitBattlerHealthboxCoords', battler)
            self.call('SetHealthboxSpriteVisible', healthbox)
            healthboxes.append(healthbox)
        icons = [self.read(self.symbols['sPartnerIconIds'] + b, 1) for b in range(4)]
        self.assertLess(icons[0], 64)
        self.assertLess(icons[2], 64)
        self.assertEqual(icons[1], 255)  # Enemy never receives a partner icon.
        sprite = self.symbols['gSprites'] + icons[0] * 68
        owner = self.symbols['gSprites'] + healthboxes[0] * 68
        self.assertEqual(self.read(sprite + 0x20, 2), self.read(owner + 0x20, 2) - 40)
        self.assertEqual(self.read(sprite + 0x22, 2), self.read(owner + 0x22, 2))
        self.call('SetHealthboxSpriteInvisible', healthboxes[0])
        self.assertTrue(self.read(sprite + 0x3e, 1) & 4)
        self.call('SetHealthboxSpriteVisible', healthboxes[0])
        self.assertFalse(self.read(sprite + 0x3e, 1) & 4)
        self.write(self.symbols['gBattlerPartyIndexes'], 1, 2)
        self.call('SetHealthboxSpriteVisible', healthboxes[0])
        switched = self.read(self.symbols['sPartnerIconIds'], 1)
        self.assertEqual(self.read(self.symbols['gSprites'] + switched * 68 + 0x2e, 2), 133)
        for healthbox in healthboxes:
            self.call('DestoryHealthboxSprite', healthbox)
        self.assertEqual(self.read(self.symbols['sPartnerIconIds'], 1), 255)
        self.assertEqual(self.read(self.symbols['sPartnerIconIds'] + 2, 1), 255)

    def test_partner_party_icons_follow_reordering_and_remote_updates(self):
        for slot, species in enumerate((25, 133, 7, 4, 1, 143)):
            self.linked_party_mon(slot, slot + 1)
            self.write(self.box + 160 + slot * 18 + 12, species, 2)
        self.call('InitPartyMenu', 0, 0, 0, 0, 0,
                  self.symbols['Task_HandleChooseMonInput'] | 1,
                  self.symbols['CB2_ReturnToField'] | 1)
        self.lib.sl_run(self.h, 100, 0)
        boxes = self.read(self.symbols['sPartyMenuBoxes'])
        def partner_species(slot):
            icon = self.read(boxes + slot * 16 + 10, 1)
            self.assertLess(icon, 64)
            return self.read(self.symbols['gSprites'] + icon * 68 + 0x2e, 2)
        self.assertEqual([partner_species(i) for i in range(6)], [25, 133, 7, 4, 1, 143])
        self.write(self.symbols['gPartyMenu'] + 9, 0, 1)
        self.write(self.symbols['gPartyMenu'] + 10, 1, 1)
        self.call('SwitchPartyMon')
        self.lib.sl_run(self.h, 2, 0)
        self.assertEqual([partner_species(i) for i in range(2)], [133, 25])
        self.write(self.box + 160 + 12, 26, 2)  # Partner evolved while menu stayed open.
        self.lib.sl_run(self.h, 2, 0)
        self.assertEqual(partner_species(1), 26)
        self.set_mon_field('MON_DATA_SOUL_ID', 0, 1)
        self.lib.sl_run(self.h, 2, 0)
        self.assertEqual(self.read(boxes + 16 + 10, 1), 255)
        self.call('FreePartyPointers')
        self.assertEqual(self.read(self.symbols['sPartyMenuBoxes']), 0)

    def enable_qol(self):
        self.write(self.box + 32, 0x1f000000)
        self.call('SoulLink_Frame')

    def set_mon_field(self, field, value, slot=0):
        scratch = 0x0203ffe0
        self.write(scratch, value)
        self.call('SetMonData', self.party + slot * 100, self.fields[field], scratch)

    def mon_field(self, field, slot=0):
        return self.call('GetMonData3', self.party + slot * 100, self.fields[field], 0)

    def test_qol_level_round_trip_preserves_identity_and_hp_ratio(self):
        self.enable_qol()
        self.linked_party_mon(0, 20)
        self.set_mon_field('MON_DATA_HP', 7)
        self.set_mon_field('MON_DATA_STATUS', 8)
        self.set_mon_field('MON_DATA_PP1', 2)
        before = {key: self.mon_field(key) for key in
                  ('MON_DATA_PERSONALITY', 'MON_DATA_OT_ID', 'MON_DATA_IVS',
                   'MON_DATA_HP_EV', 'MON_DATA_FRIENDSHIP', 'MON_DATA_SOUL_ID',
                   'MON_DATA_MOVE1', 'MON_DATA_STATUS', 'MON_DATA_PP1')}
        old_max = self.mon_field('MON_DATA_MAX_HP')
        self.assertEqual(self.call('SoulQol_SetLevel', self.party, 100), 1)
        self.assertEqual(self.mon_field('MON_DATA_LEVEL'), 100)
        new_max = self.mon_field('MON_DATA_MAX_HP')
        self.assertEqual(self.mon_field('MON_DATA_HP'), (7 * new_max + old_max - 1) // old_max)
        for key, value in before.items():
            self.assertEqual(self.mon_field(key), value, key)
        self.assertEqual(self.call('SoulQol_SetLevel', self.party, 1), 1)
        self.assertEqual(self.mon_field('MON_DATA_LEVEL'), 1)
        self.assertEqual(self.mon_field('MON_DATA_EXP'), 1)  # Emerald's level-one threshold.
        for level in (0, 101):
            self.assertEqual(self.call('SoulQol_SetLevel', self.party, level), 0)
        self.write(self.box + 32, 0)
        self.call('SoulLink_Frame')
        self.assertEqual(self.call('SoulQol_SetLevel', self.party, 50), 0)

    def test_qol_heal_and_level_protect_local_and_pending_remote_deaths(self):
        self.enable_qol()
        for slot in range(3):
            self.linked_party_mon(slot, slot + 1)
            self.set_mon_field('MON_DATA_HP', 1, slot)
            self.set_mon_field('MON_DATA_STATUS', 8, slot)
            self.set_mon_field('MON_DATA_PP1', 0, slot)
        self.write(self.save + 20 + 1, 3, 1)
        self.write(self.party + 100 + 86, 0, 2)
        self.write(self.box + 160 + 2 * 18 + 16, 3, 1)
        self.call('SoulQol_HealParty')
        self.assertEqual(self.mon_field('MON_DATA_HP'), self.mon_field('MON_DATA_MAX_HP'))
        self.assertEqual(self.mon_field('MON_DATA_STATUS'), 0)
        self.assertGreater(self.mon_field('MON_DATA_PP1'), 0)
        self.assertEqual(self.read(self.party + 100 + 86, 2), 0)
        self.assertEqual(self.read(self.party + 200 + 86, 2), 1)
        for slot in (1, 2):
            self.assertEqual(self.call('SoulQol_SetLevel', self.party + slot * 100, 50), 0)
            self.assertEqual(self.mon_field('MON_DATA_PP1', slot), 0)

    def test_qol_learn_moves_include_ancestors_but_not_siblings_or_future_moves(self):
        self.enable_qol()
        self.linked_party_mon(0, 20, species=26)  # Raichu: inherits Pikachu and Pichu.
        self.assertEqual(self.call('SoulQol_SetLevel', self.party, 30), 1)
        for i in range(4):
            self.set_mon_field('MON_DATA_MOVE' + str(i + 1), 0)
        buffer = self.call('AllocZeroed', 256)
        self.assertTrue(buffer)
        count = self.call('SoulQol_GetLearnMoves', self.party, buffer)
        moves = [self.read(buffer + 2*i, 2) for i in range(count)]
        self.assertIn(21, moves)  # Pikachu Slam, absent from Raichu learnset.
        self.assertIn(204, moves)  # Pichu Charm.
        self.assertNotIn(87, moves)  # Pikachu Thunder, level 41.
        self.assertEqual(len(moves), len(set(moves)))
        self.set_mon_field('MON_DATA_MOVE1', 98)
        count = self.call('SoulQol_GetLearnMoves', self.party, buffer)
        self.assertNotIn(98, [self.read(buffer + 2*i, 2) for i in range(count)])
        self.call('Free', buffer)

    def test_qol_party_level_picker_applies_and_returns(self):
        self.enable_qol()
        self.linked_party_mon(0, 20)
        self.call('InitPartyMenu', 0, 0, 0, 0, 0,
                  self.symbols['Task_HandleChooseMonInput'] | 1,
                  self.symbols['CB2_ReturnToFieldWithOpenMenu'] | 1)
        def press(key):
            self.lib.sl_run(self.h, 1, key)
            self.lib.sl_run(self.h, 3, 0)
        self.lib.sl_run(self.h, 80, 0)
        press(1)  # Select Pokémon.
        self.lib.sl_run(self.h, 10, 0)
        press(128); press(128); press(1)  # Summary, Item, Set Level.
        self.lib.sl_run(self.h, 60, 0)
        press(64); press(1)  # Raise from five to six and apply.
        self.lib.sl_run(self.h, 100, 0)
        self.assertEqual(self.mon_field('MON_DATA_LEVEL'), 6)
        self.assertEqual(self.read(self.symbols['gMain'] + 4) & ~1,
                         self.symbols['CB2_UpdatePartyMenu'] & ~1)

    def test_qol_pc_menu_returns_without_dialog_frame(self):
        self.call('SetMainCallback2', self.symbols['CB2_NewGame'] | 1)
        self.lib.sl_run(self.h, 600, 0)
        self.call('ScriptContext_Init')
        self.call('UnlockPlayerFieldControls')
        self.call('SoulLink_OpenTools')
        self.lib.sl_run(self.h, 60, 0)
        def press(key):
            self.lib.sl_run(self.h, 20, key)
            self.lib.sl_run(self.h, 20, 0)
        press(128); press(128); press(1)
        self.assertEqual(self.read(self.symbols['gSoulQolPc'], 1), 1)
        press(2)
        self.assertEqual(self.read(self.symbols['gSoulQolPc'], 1), 0)
        self.assertEqual(self.call('FuncIsActiveTask', self.symbols['MenuTask'] | 1), 1)
        tilemap = self.call('GetBgTilemapBuffer', 0)
        # Tools ends at row 18. The PC dialogue's bottom border must be gone.
        for x in range(30):
            self.assertEqual(self.read(tilemap + 2 * (19 * 32 + x), 2) & 0x3ff, 0)

    def test_qol_type_preview_is_pure_and_handles_dual_types(self):
        rng = self.symbols['gRngValue']
        before = self.read(rng)
        # Fire vs Grass/Bug, Water/Dragon; Normal vs Ghost; repeated Grass type.
        for args, expected in [((10, 12, 6), 400), ((10, 11, 16), 25),
                               ((0, 7, 7), 0), ((10, 12, 12), 200), ((0, 0, 0), 100)]:
            self.assertEqual(self.call('SoulQol_TypeMultiplier', *args), expected)
        self.assertEqual(self.read(rng), before)

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

    def test_stable_overworld_party_cycle_budget(self):
        self.write(self.save + 12, 32)
        self.call('ScriptContext_Init')
        self.call('UnlockPlayerFieldControls')
        ids = (512, 19, 18, 20, 61, 60)
        for slot, soul_id in enumerate(ids):
            with self.subTest(party_size=slot + 1):
                self.linked_party_mon(slot, soul_id)
                self.call('SoulLink_Overworld')  # Finish the membership change first.
                for _ in range(3):
                    before = self.lib.sl_cycles(self.h)
                    self.call('SoulLink_Overworld')
                    cycles = self.lib.sl_cycles(self.h) - before
                    # Leave over half the GBA's 280896-cycle frame for the game.
                    self.assertLess(cycles, 280896 // 2)
                self.assertEqual(self.party_ids(), list(ids[:slot + 1]))

    def test_overworld_membership_snapshot_refreshes_each_frame(self):
        self.write(self.save + 12, 32)
        self.call('ScriptContext_Init')
        self.call('UnlockPlayerFieldControls')
        self.linked_party_mon(0, 512)
        self.linked_party_mon(1, 20)
        self.call('SoulLink_Overworld')
        main = self.symbols['gMain']

        def check_keys(matches):
            self.write(main + 0x2c, 0x10, 2)  # Hold right.
            self.write(main + 0x2e, 0x19, 2)  # Right, A, Start.
            self.call('SoulLink_Overworld')
            self.assertEqual(self.read(main + 0x2c, 2), 0x10 if matches else 0)
            self.assertEqual(self.read(main + 0x2e, 2), 0x19 if matches else 9)

        check_keys(True)
        # Change local identity without changing the approved membership hash.
        self.linked_party_mon(1, 21)
        self.write(self.box + 160 + 20 * 18 + 17, 0, 1)
        check_keys(False)
        self.linked_party_mon(1, 20)
        check_keys(True)
        # An extra linked member must also restrict movement.
        self.linked_party_mon(2, 21)
        self.write(self.box + 160 + 20 * 18 + 17, 0, 1)
        check_keys(False)
        # Pending or dead unapproved members do not require party agreement.
        for state in (1, 3):
            self.write(self.save + 20 + 20, state, 1)
            check_keys(True)
        self.assertEqual(self.read(self.party + 200 + 86, 2), 0)

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

    def test_unresolved_reconciliation_recovers_when_mon_arrives(self):
        self.write(self.save + 12, 32)
        self.linked_party_mon(0, 512)
        self.call('ScriptContext_Init')
        self.call('UnlockPlayerFieldControls')
        self.call('SoulLink_Overworld')
        self.write(self.box + 160 + 19 * 18 + 17, 1, 1)
        self.write(self.save + 20 + 19, 2, 1)
        for _ in range(2):
            self.call('SoulLink_Overworld')
            self.assertEqual(self.party_ids(), [512])
        self.linked_party_mon(1, 20)
        self.call('SetBoxMonAt', 0, 0, self.party + 100)
        self.call('ZeroMonData', self.party + 100)
        self.write(self.symbols['gPlayerPartyCount'], 1, 1)
        main = self.symbols['gMain']
        self.write(main + 0x2c, 0x10, 2)
        self.call('SoulLink_Overworld')
        self.assertEqual(self.party_ids(), [512, 20])
        # Membership checks must see the withdrawal in this same update.
        self.assertEqual(self.read(main + 0x2c, 2), 0x10)

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
