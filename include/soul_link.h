#ifndef GUARD_SOUL_LINK_H
#define GUARD_SOUL_LINK_H

#define SOUL_MAGIC 0x534F554C
#define SOUL_BUILD 0x534C0001
#define SOUL_AREAS 512
#define SOUL_STARTER 511
#define SOUL_RING 16
#define SOUL_DUPES (1 << 0)
#define SOUL_SHINY (1 << 1)
#define SOUL_GENDER (1 << 2)
#define SOUL_PAIR_TYPE (1 << 3)
#define SOUL_TEAM_TYPE (1 << 4)
#define SOUL_PAIRED_PARTY (1 << 5)
#define SOUL_WIPE (1 << 6)
#define SOUL_GIFTS (1 << 7)
#define SOUL_RANDOM_WILD (1 << 8)
#define SOUL_RANDOM_STARTERS (1 << 9)
#define SOUL_SIMILAR (1 << 10)
#define SOUL_NO_LEGENDS (1 << 11)
#define SOUL_NO_BATTLE_ITEMS (1 << 12)
#define SOUL_FORCE_SET (1 << 13)
#define SOUL_START_OPTIONS (1 << 23)
#define SOUL_DEFAULT_OPTIONS (SOUL_START_OPTIONS | (2 << 14) | (1 << 16) | (1 << 17))
#define SOUL_AVAILABLE 0
#define SOUL_PENDING 1
#define SOUL_LINKED 2
#define SOUL_DEAD 3
#define SOUL_FORFEITED 4

struct SoulEvent { u32 seq, kind, args[10]; };

// Stored in unused PokemonStorage sector capacity; original Pokemon size is unchanged.
struct SoulSave
{
    u32 magic, run, seed, rules, seq;
    u8 state[SOUL_AREAS];
    u8 caught[52];
    u8 ended, player, locked, reserved;
    u32 write, read, partyHash;
    struct SoulEvent events[SOUL_RING];
};

struct SoulRemoteMon
{
    u8 name[12];
    u16 species;
    u8 type, gender, state, active;
} __attribute__((packed, aligned(2)));
// ABI v1. Only the bridge writes heartbeat, connection and inbound fields.
struct SoulMailbox
{
    u32 magic, protocol, build, frame;              // 0..12
    u32 heartbeat, connection, run, player;        // 16..28
    u32 rules, seed, locked, confirmed;            // 32..44
    u32 ended, safe, map, x, y, facing, gender, movement; // 48..76
    u32 remoteMap, remoteX, remoteY, remoteFacing;  // 80..92
    u32 remoteGender, remoteMovement, remoteVisible; // 96..104
    u32 txWrite, txRead, rxVersion, appliedVersion; // 108..120
    u32 ack;                                      // 124
    u8 trainer[8], remoteTrainer[8];               // 128..143
    u32 reserved[4];                               // 144..159
    struct SoulRemoteMon mons[SOUL_AREAS];         // 160..9375
    struct SoulEvent events[SOUL_RING];            // 9376..
};
extern volatile struct SoulMailbox gSoulLinkMailbox;
struct Pokemon;
struct BoxPokemon;
void SoulLink_Frame(void);
bool8 SoulLink_Overworld(void);
bool8 SoulLink_Blocked(struct Pokemon *mon);
bool8 SoulLink_IsDead(struct Pokemon *mon);
void SoulLink_Faint(struct Pokemon *mon);
void SoulLink_Changed(struct BoxPokemon *mon);
void SoulLink_Receive(struct Pokemon *mon);
void SoulLink_BeginEncounter(bool8 special);
void SoulLink_EndEncounter(void);
bool8 SoulLink_CanCatch(void);
u16 SoulLink_RandomSpecies(u16 species, u32 key, bool8 starter);
void SoulLink_OpenMenu(void);
bool8 SoulLink_Memo(struct Pokemon *mon, u8 *text);
void SoulLink_NewGame(void);
void SoulLink_Starter(void);
bool8 SoulLink_Enabled(void);
bool8 SoulLink_RuleEnabled(u32 rule);
void SoulLink_ApplyOptions(u32 rules);
bool8 SoulLink_AllowedMode(void);
u8 SoulLink_FindFieldMove(u16 move);
struct Pokemon *SoulLink_FieldMon(u16 index);
#endif
