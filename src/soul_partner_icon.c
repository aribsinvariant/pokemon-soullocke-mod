#include "global.h"
#include "sprite.h"
#include "pokemon_icon.h"
#include "palette.h"
#include "soul_partner_icon.h"
#include "constants/species.h"

#define PARTNER_PAL_TAG 0xF210

static const struct OamData sOam = {
    .shape = SPRITE_SHAPE(16x16),
    .size = SPRITE_SIZE(16x16),
    .priority = 1,
};
static const struct SpriteFrameImage sImage = {NULL, 4 * TILE_SIZE_4BPP};
static const struct SpriteTemplate sTemplate = {
    .tileTag = TAG_NONE,
    .paletteTag = TAG_NONE,
    .oam = &sOam,
    .anims = gDummySpriteAnimTable,
    .images = &sImage,
    .affineAnims = gDummySpriteAffineAnimTable,
    .callback = SpriteCallbackDummy,
};

static bool8 IsPartnerIcon(u8 id)
{
    return id < MAX_SPRITES && gSprites[id].inUse && gSprites[id].template == &sTemplate;
}

static void ReleasePalette(u16 tag)
{
    u8 i, palette = IndexOfSpritePaletteTag(tag);
    if (palette == 0xFF)
        return;
    for (i = 0; i < MAX_SPRITES; i++)
        if (gSprites[i].inUse && gSprites[i].oam.paletteNum == palette)
            return;
    FreeSpritePaletteByTag(tag);
}

void SoulPartnerIcon_Destroy(u8 id)
{
    if (IsPartnerIcon(id))
    {
        u16 tag = gSprites[id].data[1];
        DestroySprite(&gSprites[id]);
        if (tag != TAG_NONE)
            ReleasePalette(tag);
    }
}

u8 SoulPartnerIcon_Update(u8 id, u16 species)
{
    u8 palette, x, y;
    u16 tag, ownedTag = TAG_NONE;
    // Half-size, nearest-neighbor sampling of the first 32x32 frame.
    u32 tiles[4 * TILE_SIZE_4BPP / sizeof(u32)] = {0};
    u8 *dst = (u8 *)tiles;
    const u8 *src;
    if (IsPartnerIcon(id) && gSprites[id].data[0] == species)
        return id;
    SoulPartnerIcon_Destroy(id);
    if (!species || species >= SPECIES_EGG)
        return SPRITE_NONE;
    palette = GetValidMonIconPalIndex(species);
    tag = gMonIconPaletteTable[palette].tag;
    palette = IndexOfSpritePaletteTag(tag);
    if (palette == 0xFF)
    {
        ownedTag = PARTNER_PAL_TAG + GetValidMonIconPalIndex(species);
        palette = IndexOfSpritePaletteTag(ownedTag);
        if (palette == 0xFF)
        {
            palette = AllocSpritePalette(ownedTag);
            if (palette == 0xFF)
                return SPRITE_NONE;
            LoadPalette(GetValidMonIconPalettePtr(species), OBJ_PLTT_ID(palette), PLTT_SIZE_4BPP);
        }
    }
    id = CreateSprite(&sTemplate, 0, 0, 0);
    if (id == MAX_SPRITES)
    {
        if (ownedTag != TAG_NONE)
            ReleasePalette(ownedTag);
        return SPRITE_NONE;
    }
    gSprites[id].animPaused = TRUE;
    gSprites[id].animBeginning = FALSE;
    gSprites[id].oam.paletteNum = palette;
    gSprites[id].data[0] = species;
    gSprites[id].data[1] = ownedTag;
    src = GetMonIconTiles(species, TRUE);
    for (y = 0; y < 16; y++)
        for (x = 0; x < 16; x++)
        {
            u16 source = ((y * 2 / 8) * 4 + x * 2 / 8) * 32 + (y * 2 % 8) * 4 + x % 4;
            u16 target = ((y / 8) * 2 + x / 8) * 32 + (y % 8) * 4 + (x % 8) / 2;
            dst[target] |= (src[source] & 15) << ((x & 1) * 4);
        }
    CpuCopy16(tiles, (void *)(OBJ_VRAM0 + gSprites[id].oam.tileNum * TILE_SIZE_4BPP), sizeof(tiles));
    return id;
}

void SoulPartnerIcon_Follow(u8 id, struct Sprite *owner, s16 dx, s16 dy)
{
    if (!IsPartnerIcon(id))
        return;
    gSprites[id].x = owner->x + dx;
    gSprites[id].y = owner->y + dy;
    gSprites[id].x2 = owner->x2;
    gSprites[id].y2 = owner->y2;
    gSprites[id].invisible = owner->invisible;
    gSprites[id].oam.priority = owner->oam.priority;
    gSprites[id].subpriority = owner->subpriority;
}
