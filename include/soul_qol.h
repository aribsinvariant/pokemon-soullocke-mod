#ifndef GUARD_SOUL_QOL_H
#define GUARD_SOUL_QOL_H

struct Pokemon;
#define QOL_MAX_LEARN_MOVES 128
bool8 SoulQol_CanUse(u32 permission);
bool8 SoulQol_IsDead(struct Pokemon *mon);
void SoulLink_OpenTools(void);
bool8 SoulQol_SetLevel(struct Pokemon *mon, u8 level);
u16 SoulQol_GetLearnMoves(struct Pokemon *mon, u16 *moves);
void SoulQol_HealParty(void);
void SoulQol_OpenFlyMap(void);
extern bool8 gSoulQolPc;
void SoulQol_ReturnToTools(void);
bool8 SoulQol_IsFlying(void);
void SoulQol_FinishFly(bool8 selected);
extern bool8 gSoulQolEvolution;
u16 SoulQol_TypeMultiplier(u8 moveType, u8 type1, u8 type2);
#endif
