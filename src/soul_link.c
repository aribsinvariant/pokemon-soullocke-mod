#include "global.h"
#include "soul_link.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "main.h"
#include "overworld.h"
#include "field_player_avatar.h"
#include "event_object_movement.h"
#include "script.h"
#include "battle.h"
#include "battle_setup.h"
#include "string_util.h"
#include "strings.h"
#include "data.h"
#include "constants/characters.h"
extern const struct Evolution gEvolutionTable[NUM_SPECIES][EVOS_PER_MON];
#include "region_map.h"
#include "event_data.h"
#include "palette.h"
#include "constants/species.h"
#include "constants/moves.h"
#include "constants/battle.h"
#include "constants/flags.h"
#include "constants/event_objects.h"
#include "constants/pokemon.h"
#include "field_message_box.h"

EWRAM_DATA volatile struct SoulMailbox gSoulLinkMailbox = {0};
EWRAM_DATA static u32 sHeartbeat = 0;
EWRAM_DATA static u16 sSilence = 0;
EWRAM_DATA static u16 sEncounter = 0xFFFF;
EWRAM_DATA static bool8 sEligible = FALSE;
EWRAM_DATA static u32 sReservationSeq = 0;
EWRAM_DATA static bool8 sStarter = FALSE;
EWRAM_DATA static u8 sRemoteSprite = MAX_SPRITES;
EWRAM_DATA static u8 sRemoteGraphics = 0;
EWRAM_DATA static struct Pokemon sFieldMon = {0};


#define SAVE (&gPokemonStoragePtr->soul)
#define BOX (&gSoulLinkMailbox)

typedef char SoulRecordSize[(sizeof(struct SoulRemoteMon) == 18) ? 1 : -1];
typedef char SoulEventSize[(sizeof(struct SoulEvent) == 48) ? 1 : -1];
typedef char SoulMailboxOffset[(__builtin_offsetof(struct SoulMailbox, events) == 9376) ? 1 : -1];

static const u8 sSoulText0[] = _("Soul");
static const u8 sSoulText1[] = _("Unpaired collectible.\nCannot battle.");
static const u8 sSoulText2[] = _("Soul Link: ");
static const u8 sSoulText3[] = _("DEAD");
static const u8 sSoulText4[] = _("LINKED");
static const u8 sSoulText5[] = _("PENDING");
static const u8 sSoulText6[] = _("\n");
static const u8 sSoulText7[] = _(" / ");
static const u8 sSoulText8[] = _("Waiting for partner");
static const u8 sSoulText9[] = _("Starter pair");

bool8 SoulLink_Enabled(void)
{
    return gPokemonStoragePtr != NULL && SAVE->magic == SOUL_MAGIC;
}

bool8 SoulLink_RuleEnabled(u32 rule)
{
    return SoulLink_Enabled() && (SAVE->rules & rule) != 0;
}

void SoulLink_ApplyOptions(u32 rules)
{
    if (!(rules & SOUL_START_OPTIONS))
        return;
    gSaveBlock2Ptr->optionsTextSpeed = min((rules >> 14) & 3, 2);
    gSaveBlock2Ptr->optionsBattleStyle = (rules >> 16) & 1;
    gSaveBlock2Ptr->optionsBattleSceneOff = (rules >> 17) & 1;
    gSaveBlock2Ptr->optionsWindowFrameType = min((rules >> 18) & 31, 19);
}

void SoulLink_NewGame(void)
{
    memset(SAVE, 0, sizeof(*SAVE));
    SAVE->magic = SOUL_MAGIC;
    SAVE->rules = SOUL_DUPES | SOUL_PAIRED_PARTY | SOUL_WIPE;
    SoulLink_ApplyOptions(SOUL_DEFAULT_OPTIONS);
    SAVE->seed = 1;
    memset((void *)BOX, 0, sizeof(*BOX));
    sEncounter = 0xFFFF;
    sRemoteSprite = MAX_SPRITES;
}

static struct SoulEvent *Queue(u32 kind)
{
    struct SoulEvent *event;
    if (SAVE->write - SAVE->read >= SOUL_RING)
    {
        SAVE->reserved = 1;
        BOX->connection = 3;
        return NULL;
    }
    event = &SAVE->events[SAVE->write % SOUL_RING];
    memset(event, 0, sizeof(*event));
    event->seq = ++SAVE->seq;
    event->kind = kind;
    SAVE->write++;
    return event;
}

void SoulLink_SendSettings(u32 rules, u32 seed, bool8 confirm)
{
    struct SoulEvent *event = Queue(confirm ? 5 : 6);
    if (event != NULL)
    {
        event->args[0] = rules;
        event->args[1] = seed;
    }
}

void SoulLink_SendParty(bool8 accept)
{
    u16 i, count = 0, id;
    struct SoulEvent *event = Queue(7);
    if (event == NULL)
        return;
    if (accept)
    {
        for (i = 0; i < SOUL_AREAS && count < PARTY_SIZE; i++)
            if (BOX->mons[i].active & 2)
                event->args[++count] = i;
    }
    else
    {
        for (i = 0; i < PARTY_SIZE; i++)
        {
            id = GetMonData(&gPlayerParty[i], MON_DATA_SOUL_ID);
            if (id && id <= SOUL_AREAS && SAVE->state[id-1] == SOUL_LINKED)
                event->args[++count] = id-1;
        }
    }
    event->args[0] = count;
}

void SoulLink_Frame(void)
{
    u32 i;
    if (!SoulLink_Enabled())
        return;
    if (BOX->magic != SOUL_MAGIC)
    {
        memset((void *)BOX, 0, sizeof(*BOX));
        BOX->protocol = 1;
        BOX->build = SOUL_BUILD;
        BOX->run = SAVE->run;
        BOX->rules = SAVE->rules;
        BOX->seed = SAVE->seed;
        BOX->player = SAVE->player;
        BOX->txRead = SAVE->read;
        BOX->magic = SOUL_MAGIC; // Publish after initialization.
    }
    BOX->frame++;
    BOX->safe = gMain.callback2 == CB2_Overworld && !ScriptContext_IsEnabled()
        && !ArePlayerFieldControlsLocked() && !gPaletteFade.active;
    if (BOX->heartbeat != sHeartbeat)
    {
        sHeartbeat = BOX->heartbeat;
        sSilence = 0;
    }
    else if (++sSilence > 180)
    {
        sSilence = 181;
        BOX->connection = 0;
        BOX->remoteVisible = 0;
    }
    if (SAVE->reserved) BOX->connection = 3;
    if (SAVE->run && BOX->run != SAVE->run)
        BOX->connection = 3;
    if (BOX->connection && BOX->connection != 3 && BOX->ack > SAVE->seq)
        SAVE->seq = BOX->ack; // Ordinary save reload: replay authoritative outcomes below.
    while (SAVE->read < SAVE->write && SAVE->events[SAVE->read % SOUL_RING].seq <= BOX->ack)
        SAVE->read++;
    BOX->txRead = SAVE->read;
    for (i = SAVE->read; i != SAVE->write; i++)
        memcpy((void *)&BOX->events[i % SOUL_RING], &SAVE->events[i % SOUL_RING], sizeof(struct SoulEvent));
    BOX->txWrite = SAVE->write;
    memcpy((void *)BOX->trainer, gSaveBlock2Ptr->playerName, 8);
    if (BOX->run && BOX->connection != 3)
    {
        if (!SAVE->run || (!SAVE->locked && SAVE->rules != BOX->rules))
            SoulLink_ApplyOptions(BOX->rules);
        SAVE->run = BOX->run;
        SAVE->seed = BOX->seed;
        SAVE->rules = BOX->rules;
        SAVE->player = BOX->player;
        SAVE->locked = BOX->locked;
    }
    if (gMain.callback2 == CB2_Overworld)
    {
        BOX->map = ((u16)(u8)gSaveBlock1Ptr->location.mapGroup << 8) | (u8)gSaveBlock1Ptr->location.mapNum;
        BOX->x = gSaveBlock1Ptr->pos.x;
        BOX->y = gSaveBlock1Ptr->pos.y;
        BOX->facing = GetPlayerFacingDirection();
        BOX->gender = gSaveBlock2Ptr->playerGender;
        BOX->movement = gPlayerAvatar.flags;
    }
    else
        BOX->safe = 0;
}

bool8 SoulLink_IsDead(struct Pokemon *mon)
{
    u16 id;
    if (!SoulLink_Enabled()) return FALSE;
    id = GetMonData(mon, MON_DATA_SOUL_ID);
    return id && (id > SOUL_AREAS || SAVE->ended || SAVE->state[id-1] >= SOUL_DEAD);
}

bool8 SoulLink_Blocked(struct Pokemon *mon)
{
    u16 id;
    if (!SoulLink_Enabled())
        return FALSE;
    id = GetMonData(mon, MON_DATA_SOUL_ID);
    if (!id)
        return FALSE;
    if (id > SOUL_AREAS)
        return TRUE;
    if (SAVE->state[id-1] >= SOUL_DEAD || SAVE->ended)
        return TRUE;
    if (id == SOUL_STARTER + 1 && (gBattleTypeFlags & BATTLE_TYPE_FIRST_BATTLE) && gMain.inBattle)
        return FALSE;
    if (SAVE->state[id-1] != SOUL_LINKED)
        return TRUE;
    return (SAVE->rules & (SOUL_PAIRED_PARTY | SOUL_TEAM_TYPE)) && !(BOX->mons[id-1].active & 1);
}

void SoulLink_Faint(struct Pokemon *mon)
{
    u16 id;
    struct SoulEvent *event;
    if (!SoulLink_Enabled())
        return;
    id = GetMonData(mon, MON_DATA_SOUL_ID);
    if (!id || id > SOUL_AREAS || SAVE->state[id-1] >= SOUL_DEAD)
        return;
    event = Queue(2);
    if (event != NULL)
    {
        event->args[0] = id-1;
        SAVE->state[id-1] = SOUL_DEAD;
        mon->hp = 0;
    }
}

void SoulLink_Changed(struct BoxPokemon *mon)
{
    u16 id;
    struct SoulEvent *event;
    if (!SoulLink_Enabled()) return;
    id = GetBoxMonData(mon, MON_DATA_SOUL_ID);
    if (!id || id > SOUL_AREAS || SAVE->state[id-1] == SOUL_AVAILABLE) return;
    event = Queue(8);
    if (event == NULL) return;
    event->args[0] = id-1;
    event->args[1] = GetBoxMonData(mon, MON_DATA_SPECIES);
    event->args[2] = gSpeciesInfo[event->args[1]].types[0];
    memset(&event->args[5], 0xFF, 12);
    GetBoxMonData(mon, MON_DATA_NICKNAME, (u8 *)&event->args[5]);
}

void SoulLink_Starter(void) { sStarter = TRUE; }

static u16 Area(bool8 special)
{
    u16 area = gMapHeader.regionMapSectionId;
    if (special && (SAVE->rules & SOUL_GIFTS))
        area += 256;
    return area < SOUL_STARTER ? area : SOUL_STARTER - 1;
}

static u16 Family(u16 species)
{
    u16 i, j, parent, steps;
    for (steps = 0; steps < 10; steps++)
    {
        parent = species;
        for (i = 1; i < NUM_SPECIES; i++)
            for (j = 0; j < EVOS_PER_MON; j++)
                if (gEvolutionTable[i][j].targetSpecies == species)
                    parent = i;
        if (parent == species)
            break;
        species = parent;
    }
    return species;
}

static bool8 IsShiny(struct Pokemon *mon)
{
    u32 personality = GetMonData(mon, MON_DATA_PERSONALITY);
    u32 ot = GetMonData(mon, MON_DATA_OT_ID);
    return ((personality >> 16) ^ (personality & 0xFFFF) ^ (ot >> 16) ^ (ot & 0xFFFF)) < 8;
}

void SoulLink_BeginEncounter(bool8 special)
{
    u16 species, family;
    u8 gender;
    volatile struct SoulRemoteMon *remote;
    struct SoulEvent *event;
    if (!SoulLink_Enabled())
        return;
    if (!FlagGet(FLAG_ADVENTURE_STARTED))
    {
        sEncounter = 0xFFFF;
        sEligible = FALSE;
        return;
    }
    sEncounter = Area(special);
    sEligible = SAVE->state[sEncounter] == SOUL_AVAILABLE;
    sReservationSeq = 0;
    species = GetMonData(&gEnemyParty[0], MON_DATA_SPECIES);
    family = Family(species);
    if ((SAVE->rules & SOUL_DUPES) && (SAVE->caught[family / 8] & (1 << (family % 8))))
        sEligible = FALSE;
    remote = &BOX->mons[sEncounter];
    gender = GetMonGender(&gEnemyParty[0]);
    if (remote->species)
    {
        if ((SAVE->rules & SOUL_GENDER) && gender != MON_GENDERLESS && remote->gender != MON_GENDERLESS && gender == remote->gender)
            sEligible = FALSE;
        if ((SAVE->rules & SOUL_PAIR_TYPE) && gSpeciesInfo[species].types[0] == remote->type)
            sEligible = FALSE;
    }
    if (sEligible)
    {
        event = Queue(9);
        if (event != NULL)
        {
            sReservationSeq = event->seq;
            event->args[0] = sEncounter;
            event->args[1] = species;
            event->args[2] = gSpeciesInfo[species].types[0];
            event->args[3] = gender;
            event->args[4] = 0;
            memset(&event->args[5], 0xFF, 12);
        }
    }
}

bool8 SoulLink_CanCatch(void)
{
    if (!SoulLink_Enabled() || (gBattleTypeFlags & BATTLE_TYPE_WALLY_TUTORIAL))
        return TRUE;
    return (sEligible && BOX->ack >= sReservationSeq && (BOX->mons[sEncounter].active & 4)) || ((SAVE->rules & SOUL_SHINY) && IsShiny(&gEnemyParty[0]));
}

void SoulLink_Receive(struct Pokemon *mon)
{
    u16 area, id, species, family;
    struct SoulEvent *event;
    u8 name[12];
    if (!SoulLink_Enabled())
        return;
    area = sStarter ? SOUL_STARTER : sEncounter != 0xFFFF ? sEncounter : Area(TRUE);
    sStarter = FALSE;
    id = area + 1;
    species = GetMonData(mon, MON_DATA_SPECIES);
    family = Family(species);
    if (area != SOUL_STARTER)
    {
        u8 gender = GetMonGender(mon);
        if ((SAVE->rules & SOUL_DUPES) && (SAVE->caught[family / 8] & (1 << (family % 8)))) id = 0xFFFF;
        if (BOX->mons[area].species)
        {
            if ((SAVE->rules & SOUL_GENDER) && gender != MON_GENDERLESS && BOX->mons[area].gender != MON_GENDERLESS
                && gender == BOX->mons[area].gender) id = 0xFFFF;
            if ((SAVE->rules & SOUL_PAIR_TYPE) && gSpeciesInfo[species].types[0] == BOX->mons[area].type) id = 0xFFFF;
        }
    }
    if (SAVE->state[area] != SOUL_AVAILABLE || (sEncounter != 0xFFFF && (!sEligible || !(BOX->mons[area].active & 4))))
        id = 0xFFFF;
    SetMonData(mon, MON_DATA_SOUL_ID, &id);
    if (id == 0xFFFF)
        return;
    species = GetMonData(mon, MON_DATA_SPECIES);
    family = Family(species);
    SAVE->caught[family / 8] |= 1 << (family % 8);
    GetMonData(mon, MON_DATA_NICKNAME, name);
    if (StringCompare(name, gSpeciesNames[species]) == 0)
    {
        u8 *end = StringCopy(name, sSoulText0);
        ConvertIntToDecimalStringN(end, id, STR_CONV_MODE_LEADING_ZEROS, 3);
        SetMonData(mon, MON_DATA_NICKNAME, name);
    }
    event = Queue(1);
    if (event == NULL)
        return;
    event->args[0] = area;
    event->args[1] = species;
    event->args[2] = gSpeciesInfo[species].types[0];
    event->args[3] = GetMonGender(mon);
    event->args[4] = gPlayerPartyCount < PARTY_SIZE;
    memset(&event->args[5], EOS, 12);
    GetMonData(mon, MON_DATA_NICKNAME, (u8 *)&event->args[5]);
    SAVE->state[area] = SOUL_PENDING;
}

void SoulLink_EndEncounter(void)
{
    struct SoulEvent *event;
    if (!SoulLink_Enabled())
        return;
    if (sEncounter != 0xFFFF && sReservationSeq)
    {
        event = Queue(11);
        if (event != NULL) event->args[0] = sEncounter;
    }
    sEncounter = 0xFFFF;
    sEligible = FALSE;
}

static void RemoteSpriteCallback(struct Sprite *sprite)
{
    s16 x, y;
    if (!BOX->remoteVisible || BOX->connection != 2 || BOX->remoteMap != BOX->map)
    {
        sprite->invisible = TRUE;
        return;
    }
    SetSpritePosToMapCoords(BOX->remoteX + 7, BOX->remoteY + 7, &x, &y);
    sprite->x = x + 8;
    sprite->y = y + 16 + sprite->centerToCornerVecY;
    sprite->coordOffsetEnabled = TRUE;
    sprite->invisible = FALSE;
    {
        u8 animation = BOX->remoteFacing > 0 && BOX->remoteFacing <= 4 ? BOX->remoteFacing - 1 : 0;
        if (sprite->data[0] != BOX->remoteX || sprite->data[1] != BOX->remoteY) sprite->data[2] = 12;
        sprite->data[0] = BOX->remoteX; sprite->data[1] = BOX->remoteY;
        if (sprite->data[2] > 0) { animation += 4; sprite->data[2]--; }
        StartSpriteAnimIfDifferent(sprite, animation);
    }
}

static void UpdateRemoteSprite(void)
{
    u8 graphics = BOX->remoteGender ? OBJ_EVENT_GFX_RIVAL_MAY_NORMAL : OBJ_EVENT_GFX_RIVAL_BRENDAN_NORMAL;
    if (BOX->remoteMovement & PLAYER_AVATAR_FLAG_SURFING)
        graphics = BOX->remoteGender ? OBJ_EVENT_GFX_RIVAL_MAY_SURFING : OBJ_EVENT_GFX_RIVAL_BRENDAN_SURFING;
    else if (BOX->remoteMovement & PLAYER_AVATAR_FLAG_MACH_BIKE)
        graphics = BOX->remoteGender ? OBJ_EVENT_GFX_RIVAL_MAY_MACH_BIKE : OBJ_EVENT_GFX_RIVAL_BRENDAN_MACH_BIKE;
    else if (BOX->remoteMovement & PLAYER_AVATAR_FLAG_ACRO_BIKE)
        graphics = BOX->remoteGender ? OBJ_EVENT_GFX_RIVAL_MAY_ACRO_BIKE : OBJ_EVENT_GFX_RIVAL_BRENDAN_ACRO_BIKE;
    if (sRemoteSprite < MAX_SPRITES && gSprites[sRemoteSprite].inUse && gSprites[sRemoteSprite].callback == RemoteSpriteCallback)
    {
        if (sRemoteGraphics == graphics)
            return;
        DestroySprite(&gSprites[sRemoteSprite]);
    }
    sRemoteSprite = MAX_SPRITES;
    if (BOX->remoteVisible && BOX->remoteMap == BOX->map)
    {
        sRemoteSprite = CreateObjectGraphicsSprite(graphics, RemoteSpriteCallback, 0, 0, 1);
        sRemoteGraphics = graphics;
    }
}

static bool8 Approved(u16 id)
{
    return id && id <= SOUL_AREAS && (BOX->mons[id-1].active & 1);
}

static bool8 PartyMatches(void)
{
    u16 i, j, id;
    if (!(SAVE->rules & (SOUL_PAIRED_PARTY | SOUL_TEAM_TYPE))) return TRUE;
    for (i = 0; i < SOUL_AREAS; i++)
    {
        if (!(BOX->mons[i].active & 1) || SAVE->state[i] >= SOUL_DEAD) continue;
        for (j = 0; j < PARTY_SIZE; j++)
            if (GetMonData(&gPlayerParty[j], MON_DATA_SOUL_ID) == i+1) break;
        if (j == PARTY_SIZE) return FALSE;
    }
    for (i = 0; i < PARTY_SIZE; i++)
    {
        id = GetMonData(&gPlayerParty[i], MON_DATA_SOUL_ID);
        if (id && id <= SOUL_AREAS && SAVE->state[id-1] == SOUL_LINKED && !Approved(id)) return FALSE;
    }
    return TRUE;
}

static void ReconcileParty(void)
{
    struct Pokemon party[PARTY_SIZE];
    u16 ids[PARTY_SIZE], count = 0, kept = 0, i, j, box, slot, id, found, freeSlots = 0, withdraw = 0, deposit = 0;
    u32 hash = 2166136261u;
    if (!(SAVE->rules & (SOUL_PAIRED_PARTY | SOUL_TEAM_TYPE)) || SAVE->state[SOUL_STARTER] < SOUL_LINKED) return;
    for (i = 0; i < SOUL_AREAS; i++)
        if (BOX->mons[i].active & 1)
        {
            if (count == PARTY_SIZE) { BOX->connection = 3; return; }
            ids[count++] = i+1;
            hash = (hash ^ (i+1)) * 16777619u;
        }
    if (hash == SAVE->partyHash || count == 0) return;
    memset(party, 0, sizeof(party));
    // Agreement controls membership, while each player controls their battle order.
    for (i = 0; i < PARTY_SIZE; i++)
    {
        id = GetMonData(&gPlayerParty[i], MON_DATA_SOUL_ID);
        if (GetMonData(&gPlayerParty[i], MON_DATA_SPECIES) && Approved(id))
            party[kept++] = gPlayerParty[i];
    }
    for (i = 0; i < count; i++)
    {
        found = FALSE;
        for (j = 0; j < PARTY_SIZE; j++)
            if (GetMonData(&gPlayerParty[j], MON_DATA_SOUL_ID) == ids[i])
            { found = TRUE; break; }
        if (found) continue;
        for (box = 0; box < TOTAL_BOXES_COUNT && !found; box++)
            for (slot = 0; slot < IN_BOX_COUNT; slot++)
                if (GetBoxMonDataAt(box, slot, MON_DATA_SOUL_ID) == ids[i])
                { BoxMonAtToMon(box, slot, &party[kept++]); found = TRUE; withdraw++; break; }
        if (!found) return;
    }
    for (box = 0; box < TOTAL_BOXES_COUNT; box++)
        for (slot = 0; slot < IN_BOX_COUNT; slot++)
            if (!GetBoxMonDataAt(box, slot, MON_DATA_SPECIES)) freeSlots++;
    for (i = 0; i < PARTY_SIZE; i++)
        if (GetMonData(&gPlayerParty[i], MON_DATA_SPECIES) && !Approved(GetMonData(&gPlayerParty[i], MON_DATA_SOUL_ID))) deposit++;
    if (deposit > freeSlots + withdraw) return;
    for (box = 0; box < TOTAL_BOXES_COUNT; box++)
        for (slot = 0; slot < IN_BOX_COUNT; slot++)
            if (Approved(GetBoxMonDataAt(box, slot, MON_DATA_SOUL_ID))) ZeroBoxMonAt(box, slot);
    for (i = 0; i < PARTY_SIZE; i++)
    {
        if (!GetMonData(&gPlayerParty[i], MON_DATA_SPECIES) || Approved(GetMonData(&gPlayerParty[i], MON_DATA_SOUL_ID))) continue;
        found = FALSE;
        for (box = 0; box < TOTAL_BOXES_COUNT && !found; box++)
            for (slot = 0; slot < IN_BOX_COUNT; slot++)
                if (!GetBoxMonDataAt(box, slot, MON_DATA_SPECIES))
                { SetBoxMonAt(box, slot, &gPlayerParty[i].box); found = TRUE; break; }
    }
    memcpy(gPlayerParty, party, sizeof(party));
    gPlayerPartyCount = count;
    SAVE->partyHash = hash;
}

bool8 SoulLink_Overworld(void)
{
    u16 i, j, id;
    bool8 alive = FALSE, any = FALSE;
    if (!SoulLink_Enabled())
        return FALSE;
    UpdateRemoteSprite();
    if (ArePlayerFieldControlsLocked() || ScriptContext_IsEnabled() || gPaletteFade.active)
        return FALSE;
    if (BOX->connection == 2 && BOX->rxVersion != BOX->appliedVersion)
    {
        for (i = 0; i < SOUL_AREAS; i++)
        {
            if (SAVE->state[i] == SOUL_AVAILABLE && BOX->mons[i].state == SOUL_LINKED)
            {
                // This save predates an already committed catch; do not recreate it or allow recatching.
                SAVE->reserved = 1;
                BOX->connection = 3;
                return TRUE;
            }
            // Never revive a locally recorded death or forget a queued catch.
            if (SAVE->state[i] < SOUL_DEAD && BOX->mons[i].state >= SOUL_LINKED)
            {
                if (SAVE->state[i] == SOUL_PENDING && BOX->mons[i].state == SOUL_LINKED
                    && !SAVE->ended && !BOX->ended)
                {
                    // Pending HP is masked to zero and may have been written back by game routines.
                    // Boxed mons regain HP on withdrawal; restore only zero-HP party mons here.
                    for (j = 0; j < PARTY_SIZE; j++)
                        if (GetMonData(&gPlayerParty[j], MON_DATA_SOUL_ID) == i+1 && gPlayerParty[j].hp == 0)
                            gPlayerParty[j].hp = gPlayerParty[j].maxHP;
                }
                SAVE->state[i] = BOX->mons[i].state;
            }
        }
        SAVE->ended |= BOX->ended;
        BOX->appliedVersion = BOX->rxVersion;
    }
    ReconcileParty();
    if (JOY_NEW(SELECT_BUTTON))
    {
        SoulLink_OpenMenu();
        return TRUE;
    }
    if (!PartyMatches())
    {
        // Still permit PC interaction and menus while waiting for party agreement.
        gMain.newKeys &= A_BUTTON | START_BUTTON;
        gMain.heldKeys = 0;
    }
    for (i = 0; i < PARTY_SIZE; i++)
    {
        id = GetMonData(&gPlayerParty[i], MON_DATA_SOUL_ID);
        if (id && id <= SOUL_AREAS)
        {
            any = TRUE;
            if (SAVE->state[id-1] >= SOUL_DEAD)
                gPlayerParty[i].hp = 0;
            if (SAVE->state[id-1] < SOUL_DEAD)
                alive = TRUE;
        }
    }
    if (any && !alive && !SAVE->ended && (SAVE->rules & SOUL_WIPE))
    {
        Queue(4);
        SAVE->ended = TRUE;
    }
    if (BOX->connection != 2 || !SAVE->locked || SAVE->ended || SAVE->read != SAVE->write
        || SAVE->state[SOUL_STARTER] == SOUL_PENDING)
    {
        // Saving and viewing the party remain available while progression is paused.
        if (JOY_NEW(START_BUTTON)) { gMain.newKeys = START_BUTTON; gMain.heldKeys = 0; return FALSE; }
        return TRUE;
    }
    return FALSE;
}

static u32 Mix(u32 value)
{
    value ^= value >> 16;
    value *= 0x7FEB352D;
    value ^= value >> 15;
    value *= 0x846CA68B;
    return value ^ (value >> 16);
}

static bool8 Legendary(u16 species)
{
    return (species >= SPECIES_ARTICUNO && species <= SPECIES_MOLTRES)
        || species == SPECIES_MEWTWO || species == SPECIES_MEW
        || (species >= SPECIES_RAIKOU && species <= SPECIES_SUICUNE)
        || (species >= SPECIES_LUGIA && species <= SPECIES_CELEBI)
        || (species >= SPECIES_REGIROCK && species <= SPECIES_REGISTEEL)
        || (species >= SPECIES_KYOGRE && species <= SPECIES_DEOXYS)
        || species == SPECIES_LATIAS || species == SPECIES_LATIOS;
}

static u16 Strength(u16 species)
{
    const struct SpeciesInfo *info = &gSpeciesInfo[species];
    return info->baseHP + info->baseAttack + info->baseDefense + info->baseSpeed + info->baseSpAttack + info->baseSpDefense;
}

u16 SoulLink_RandomSpecies(u16 species, u32 key, bool8 starter)
{
    u16 candidate, best = species, delta, bestDelta = 0xFFFF, target;
    u32 random, score, bestScore = 0;
    if (!SoulLink_Enabled() || !(SAVE->rules & (starter ? SOUL_RANDOM_STARTERS : SOUL_RANDOM_WILD)))
        return species;
    random = Mix(SAVE->seed ^ key ^ ((SAVE->player + 1) * 0x9E3779B9));
    target = Strength(species);
    for (candidate = 1; candidate < NUM_SPECIES; candidate++)
    {
        if (!SpeciesToNationalPokedexNum(candidate) || candidate == SPECIES_EGG
            || (candidate >= SPECIES_OLD_UNOWN_B && candidate <= SPECIES_OLD_UNOWN_Z)
            || ((SAVE->rules & SOUL_NO_LEGENDS) && Legendary(candidate)))
            continue;
        delta = abs((s16)Strength(candidate) - (s16)target);
        score = Mix(random ^ candidate);
        // The nearest 50-point BST band preserves variety between equal-strength species.
        if (!(SAVE->rules & SOUL_SIMILAR))
            delta = 0;
        else
            delta /= 50;
        if (delta < bestDelta || (delta == bestDelta && score > bestScore))
        {
            best = candidate;
            bestDelta = delta;
            bestScore = score;
        }
    }
    return best;
}

bool8 SoulLink_Memo(struct Pokemon *mon, u8 *text)
{
    u16 id;
    u8 *end;
    if (!SoulLink_Enabled())
        return FALSE;
    id = GetMonData(mon, MON_DATA_SOUL_ID);
    if (!id)
        return FALSE;
    if (id > SOUL_AREAS)
    {
        StringCopy(text, sSoulText1);
        return TRUE;
    }
    end = StringCopy(text, sSoulText2);
    end = StringCopy(end, SAVE->state[id-1] >= SOUL_DEAD ? sSoulText3 : SAVE->state[id-1] == SOUL_LINKED ? sSoulText4 : sSoulText5);
    end = StringCopy(end, sSoulText6);
    if (BOX->mons[id-1].species && BOX->mons[id-1].species < NUM_SPECIES)
    {
        end = StringCopy(end, (const u8 *)BOX->remoteTrainer);
        end = StringCopy(end, sSoulText7);
        end = StringCopy(end, (const u8 *)BOX->mons[id-1].name);
        end = StringCopy(end, sSoulText6);
        end = StringCopy(end, gSpeciesNames[BOX->mons[id-1].species]);
    }
    else
        end = StringCopy(end, sSoulText8);
    end = StringCopy(end, sSoulText6);
    if (id-1 == SOUL_STARTER)
        StringCopy(end, sSoulText9);
    else
        GetMapName(end, (id-1) % 256, 0);
    return TRUE;
}

bool8 SoulLink_AllowedMode(void) { return !SoulLink_Enabled(); }

// Index 7 is a field-animation-only surrogate; it never enters the player's party.
struct Pokemon *SoulLink_FieldMon(u16 index)
{
    return index == PARTY_SIZE+1 && SoulLink_Enabled() ? &sFieldMon : &gPlayerParty[index % PARTY_SIZE];
}

u8 SoulLink_FindFieldMove(u16 move)
{
    u16 box, slot, m;
    if (!SoulLink_Enabled() || (move != MOVE_CUT && move != MOVE_SURF && move != MOVE_STRENGTH
        && move != MOVE_ROCK_SMASH && move != MOVE_WATERFALL && move != MOVE_DIVE && move != MOVE_FLASH)) return PARTY_SIZE;
    for (box = 0; box < TOTAL_BOXES_COUNT; box++)
        for (slot = 0; slot < IN_BOX_COUNT; slot++)
        {
            if (!GetBoxMonDataAt(box, slot, MON_DATA_SPECIES) || GetBoxMonDataAt(box, slot, MON_DATA_IS_EGG)) continue;
            for (m = 0; m < MAX_MON_MOVES; m++)
                if (GetBoxMonDataAt(box, slot, MON_DATA_MOVE1+m) == move)
                {
                    BoxMonAtToMon(box, slot, &sFieldMon);
                    return PARTY_SIZE+1;
                }
        }
    return PARTY_SIZE;
}
