#ifndef GUARD_SOUL_PARTNER_ICON_H
#define GUARD_SOUL_PARTNER_ICON_H

struct Sprite;
// Returns SPRITE_NONE if graphics resources are unavailable.
u8 SoulPartnerIcon_Update(u8 spriteId, u16 species);
void SoulPartnerIcon_Destroy(u8 spriteId);
void SoulPartnerIcon_Follow(u8 spriteId, struct Sprite *owner, s16 dx, s16 dy);

#endif
