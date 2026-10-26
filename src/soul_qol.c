#include "global.h"
#include "soul_qol.h"
#include "soul_link.h"
#include "pokemon.h"
#include "data.h"
#include "main.h"
#include "region_map.h"
#include "overworld.h"
#include "field_screen_effect.h"
#include "event_data.h"
#include "script.h"
#include "task.h"
#include "field_weather.h"
#include "window.h"
#include "battle_pike.h"
#include "battle_pyramid.h"
#include "union_room.h"
#include "safari_zone.h"
#include "field_specials.h"
#include "constants/battle_frontier.h"
#include "battle_main.h"
#include "constants/battle.h"
#include "constants/pokemon.h"

extern const struct Evolution gEvolutionTable[NUM_SPECIES][EVOS_PER_MON];

EWRAM_DATA bool8 gSoulQolPc = FALSE;
EWRAM_DATA bool8 gSoulQolEvolution = FALSE;
static EWRAM_DATA bool8 sQolFlying = FALSE;

bool8 SoulQol_CanUse(u32 permission)
{
    return !gMain.inBattle && !IsOverworldLinkActive() && !InUnionRoom()
        && !GetSafariZoneFlag() && !InBattlePike()
        && CurrentBattlePyramidLocation() == PYRAMID_LOCATION_NONE
        && !InMultiPartnerRoom() && SoulLink_RuleEnabled(permission);
}

bool8 SoulQol_IsDead(struct Pokemon *mon)
{
    u16 id = GetMonData(mon, MON_DATA_SOUL_ID);
    return SoulLink_IsDead(mon) || (SoulLink_Enabled() && (gSoulLinkMailbox.ended
        || (id && id <= SOUL_AREAS && gSoulLinkMailbox.mons[id - 1].state >= SOUL_DEAD)));
}

bool8 SoulQol_SetLevel(struct Pokemon *mon, u8 level)
{
    u16 species, oldHp, oldMax, hp;
    u32 experience;
    if (!SoulQol_CanUse(SOUL_QOL_LEVEL) || level < 1 || level > MAX_LEVEL
        || GetMonData(mon, MON_DATA_IS_EGG) || SoulQol_IsDead(mon))
        return FALSE;
    species = GetMonData(mon, MON_DATA_SPECIES);
    if (species == SPECIES_NONE || species >= NUM_SPECIES)
        return FALSE;
    // Read real HP: MON_DATA_HP deliberately masks temporarily blocked partners.
    oldHp = mon->hp;
    oldMax = mon->maxHP;
    experience = gExperienceTables[gSpeciesInfo[species].growthRate][level];
    SetMonData(mon, MON_DATA_EXP, &experience);
    CalculateMonStats(mon);
    hp = oldMax ? ((u32)oldHp * mon->maxHP + oldMax - 1) / oldMax : 0;
    if (hp > mon->maxHP) hp = mon->maxHP;
    SetMonData(mon, MON_DATA_HP, &hp);
    return TRUE;
}

void SoulQol_HealParty(void)
{
    u8 i, j, pp;
    u32 status = 0;
    if (!SoulQol_CanUse(SOUL_QOL_HEAL)) return;
    for (i = 0; i < gPlayerPartyCount; i++)
    {
        struct Pokemon *mon = &gPlayerParty[i];
        if (GetMonData(mon, MON_DATA_IS_EGG) || SoulQol_IsDead(mon)) continue;
        SetMonData(mon, MON_DATA_HP, &mon->maxHP);
        SetMonData(mon, MON_DATA_STATUS, &status);
        for (j = 0; j < MAX_MON_MOVES; j++)
        {
            pp = CalculatePPWithBonus(GetMonData(mon, MON_DATA_MOVE1 + j), GetMonData(mon, MON_DATA_PP_BONUSES), j);
            SetMonData(mon, MON_DATA_PP1 + j, &pp);
        }
    }
}

// Walk only backwards through evolution edges, never into sibling branches.
static u16 AddLearnMoves(struct Pokemon *mon, u16 species, u16 *moves, u16 count, u8 depth)
{
    u16 i, j, move, ancestor;
    u8 evo, level = GetMonData(mon, MON_DATA_LEVEL);
    if (depth > 3) return count;
    for (i = 0; gLevelUpLearnsets[species][i] != LEVEL_UP_END; i++)
    {
        if ((gLevelUpLearnsets[species][i] >> 9) > level) continue;
        move = gLevelUpLearnsets[species][i] & LEVEL_UP_MOVE_ID;
        for (j = 0; j < MAX_MON_MOVES; j++)
            if (GetMonData(mon, MON_DATA_MOVE1 + j) == move) break;
        if (j != MAX_MON_MOVES) continue;
        for (j = 0; j < count; j++) if (moves[j] == move) break;
        if (j == count && count < QOL_MAX_LEARN_MOVES) moves[count++] = move;
    }
    for (ancestor = 1; ancestor < NUM_SPECIES; ancestor++)
        for (evo = 0; evo < EVOS_PER_MON; evo++)
            if (gEvolutionTable[ancestor][evo].targetSpecies == species)
            {
                count = AddLearnMoves(mon, ancestor, moves, count, depth + 1);
                break;
            }
    return count;
}

u16 SoulQol_GetLearnMoves(struct Pokemon *mon, u16 *moves)
{
    u16 species = GetMonData(mon, MON_DATA_SPECIES);
    if (!SoulQol_CanUse(SOUL_QOL_MOVES) || !species || species >= NUM_SPECIES
        || GetMonData(mon, MON_DATA_IS_EGG) || SoulQol_IsDead(mon)) return 0;
    return AddLearnMoves(mon, species, moves, 0, 0);
}

static void Task_ReturnTools(u8 taskId)
{
    if (!IsWeatherNotFadingIn()) return;
    DestroyTask(taskId);
    SoulLink_OpenTools();
}

static void ReturnToolsField(void)
{
    Overworld_PlaySpecialMapMusic();
    FadeInFromBlack();
    LockPlayerFieldControls();
    CreateTask(Task_ReturnTools, 10);
}

void SoulQol_ReturnToTools(void)
{
    gFieldCallback = ReturnToolsField;
    SetMainCallback2(CB2_ReturnToField);
}

void SoulQol_OpenFlyMap(void)
{
    CleanupOverworldWindowsAndTilemaps();
    sQolFlying = TRUE;
    SetMainCallback2(CB2_OpenFlyMap);
}

bool8 SoulQol_IsFlying(void) { return sQolFlying; }

void SoulQol_FinishFly(bool8 selected)
{
    sQolFlying = FALSE;
    if (selected && SoulQol_CanUse(SOUL_QOL_TELEPORT))
    {
        ResetInitialPlayerAvatarState();
        WarpIntoMap();
        gFieldCallback = FieldCB_DefaultWarpExit;
        SetMainCallback2(CB2_LoadMap);
    }
    else SoulQol_ReturnToTools();
}

// 100 = neutral. Pure type-chart lookup; never touches battle globals or RNG.
u16 SoulQol_TypeMultiplier(u8 moveType, u8 type1, u8 type2)
{
    u16 i, multiplier = 100;
    for (i = 0; gTypeEffectiveness[i] != TYPE_ENDTABLE; i += 3)
    {
        if (gTypeEffectiveness[i] == TYPE_FORESIGHT) continue;
        if (gTypeEffectiveness[i] == moveType)
        {
            if (gTypeEffectiveness[i + 1] == type1)
                multiplier = multiplier * gTypeEffectiveness[i + 2] / 10;
            if (type2 != type1 && gTypeEffectiveness[i + 1] == type2)
                multiplier = multiplier * gTypeEffectiveness[i + 2] / 10;
        }
    }
    return multiplier;
}
