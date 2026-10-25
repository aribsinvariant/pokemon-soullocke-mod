#include "global.h"
#include "soul_link.h"
#include "pokemon.h"
#include "pokemon_storage_system.h"
#include "main.h"
#include "task.h"
#include "window.h"
#include "text.h"
#include "menu.h"
#include "script.h"
#include "string_util.h"
#include "region_map.h"
#include "constants/rgb.h"

void SoulLink_SendSettings(u32 rules, u32 seed, bool8 confirm);
void SoulLink_SendParty(bool8 accept);
static void MenuTask(u8 taskId);
static void Draw(u8 taskId);

static const struct WindowTemplate sWindow = { .bg = 0, .tilemapLeft = 1, .tilemapTop = 1,
    .width = 28, .height = 18, .paletteNum = 15, .baseBlock = 0x100 };
static const u8 sColors[] = { TEXT_COLOR_WHITE, TEXT_COLOR_DARK_GRAY, TEXT_COLOR_LIGHT_GRAY };
static const u8 sPartyTitle[] = _("Partner requested party:");
static const u8 sNoParty[] = _("No pending party request.");
static const u8 sPartyHelp[] = _("R: accept   L: encounters   B: close");
static const u8 sPartyRejected[] = _("Party rejected: check links and types.");
static const u8 sTitle[] = _("SOUL LINK");
static const u8 sRule0[] = _("Duplicate family rerolls");
static const u8 sRule1[] = _("Shiny collectibles");
static const u8 sRule2[] = _("Opposite genders");
static const u8 sRule3[] = _("Different pair types");
static const u8 sRule4[] = _("Unique team types");
static const u8 sRule5[] = _("Paired party membership");
static const u8 sRule6[] = _("Wipe ends run");
static const u8 sRule7[] = _("Separate gift allowance");
static const u8 sRule8[] = _("Random wild encounters");
static const u8 sRule9[] = _("Random starters");
static const u8 sRule10[] = _("Similar strength");
static const u8 sRule11[] = _("Exclude legendaries");
static const u8 sRule12[] = _("No battle bag items");
static const u8 sRule13[] = _("Force Set battle style");
static const u8 sTextSpeed[] = _("Text: ");
static const u8 sStyle[] = _("Style: ");
static const u8 sAnimations[] = _("Animations off: ");
static const u8 sFrame[] = _("Text box: ");
static const u8 sSlow[] = _("Slow");
static const u8 sMedium[] = _("Medium");
static const u8 sFast[] = _("Fast");
static const u8 sShift[] = _("Shift");
static const u8 sSet[] = _("Set");
static const u8 *const sRules[] = {sRule0,sRule1,sRule2,sRule3,sRule4,sRule5,sRule6,sRule7,sRule8,sRule9,sRule10,sRule11,sRule12,sRule13};

static const u8 sSoulText0[] = _("Sync error: see emulator console");
static const u8 sSoulText1[] = _("Both players connected");
static const u8 sSoulText2[] = _("Waiting for connection / partner");
static const u8 sSoulText3[] = _("Host: LEFT/RIGHT change, UP/DOWN select");
static const u8 sSoulText4[] = _("> ");
static const u8 sSoulText5[] = _("  ");
static const u8 sSoulText6[] = _(" ON");
static const u8 sSoulText7[] = _(" OFF");
static const u8 sSoulText8[] = _("Seed: ");
static const u8 sSoulText9[] = _("Confirmed - waiting for partner");
static const u8 sSoulText10[] = _("A: confirm these settings");
static const u8 sSoulText11[] = _("B: close  L: party  SELECT: reopen");
static const u8 sSoulText12[] = _("Starter pair");
static const u8 sSoulText13[] = _("Gift/static allowance");
static const u8 sSoulText14[] = _("Encounter allowance");
static const u8 sSoulText15[] = _("Your partner is waiting for your catch");
static const u8 sSoulText16[] = _("Available");
static const u8 sSoulText17[] = _("Pending partner catch");
static const u8 sSoulText18[] = _("Linked");
static const u8 sSoulText19[] = _("Dead - permanently unusable");
static const u8 sSoulText20[] = _("Encounter forfeited");
static const u8 sSoulText21[] = _(" / ");
static const u8 sSoulText22[] = _("This run has ended.");
static const u8 sSoulText23[] = _("A: propose current party   R: accept party");
static const u8 sSoulText24[] = _("LEFT/RIGHT: area   UP/DOWN: next used");

static void Print(u8 window, const u8 *text, u8 y)
{
    AddTextPrinterParameterized4(window, FONT_SMALL, 2, y, 0, 0, sColors, TEXT_SKIP_DRAW, text);
}

void SoulLink_OpenMenu(void)
{
    u8 task, window;
    if (FuncIsActiveTask(MenuTask))
        return;
    window = AddWindow(&sWindow);
    if (window == WINDOW_NONE)
        return;
    task = CreateTask(MenuTask, 0);
    if (task == TASK_NONE)
    {
        RemoveWindow(window);
        return;
    }
    gTasks[task].data[0] = window;
    gTasks[task].data[1] = 0;
    gTasks[task].data[2] = 0;
    LockPlayerFieldControls();
    Draw(task);
}

static void Draw(u8 taskId)
{
    struct Task *task = &gTasks[taskId];
    u8 win = task->data[0], line;
    u16 area = task->data[1], i, selection = task->data[2];
    u8 buffer[100], *end;
    volatile struct SoulMailbox *box = &gSoulLinkMailbox;
    FillWindowPixelBuffer(win, PIXEL_FILL(1));
    Print(win, sTitle, 0);
    Print(win, box->connection == 3 ? sSoulText0 : box->connection == 2 ? sSoulText1 : sSoulText2, 14);
    if (!box->locked)
    {
        Print(win, sSoulText3, 30);
        for (line = 0; line < 4; line++)
        {
            i = (selection / 4) * 4 + line;
            if (i >= 20)
                break;
            end = StringCopy(buffer, i == selection ? sSoulText4 : sSoulText5);
            if (i < 14)
            {
                end = StringCopy(end, sRules[i]);
                StringCopy(end, box->rules & (1 << i) ? sSoulText6 : sSoulText7);
            }
            else if (i < 18)
            {
                u32 options = box->rules & SOUL_START_OPTIONS ? box->rules : SOUL_DEFAULT_OPTIONS;
                if (i == 14)
                {
                    end = StringCopy(end, sTextSpeed);
                    StringCopy(end, ((options >> 14) & 3) == 0 ? sSlow : ((options >> 14) & 3) == 1 ? sMedium : sFast);
                }
                else if (i == 15)
                {
                    end = StringCopy(end, sStyle);
                    StringCopy(end, options & (1 << 16) ? sSet : sShift);
                }
                else if (i == 16)
                {
                    end = StringCopy(end, sAnimations);
                    StringCopy(end, options & (1 << 17) ? sSoulText6 : sSoulText7);
                }
                else
                {
                    end = StringCopy(end, sFrame);
                    ConvertIntToDecimalStringN(end, ((options >> 18) & 31) + 1, STR_CONV_MODE_LEFT_ALIGN, 2);
                }
            }
            else if (i == 18)
            {
                end = StringCopy(end, sSoulText8);
                ConvertIntToDecimalStringN(end, box->seed, STR_CONV_MODE_LEFT_ALIGN, 10);
            }
            else
                StringCopy(end, box->confirmed ? sSoulText9 : sSoulText10);
            Print(win, buffer, 46 + line * 16);
        }
        Print(win, sSoulText11, 126);
    }
    else if (task->data[4])
    {
        Print(win, sPartyTitle, 30);
        line = 0;
        for (i = 0; i < SOUL_AREAS && line < 6; i++)
            if (box->mons[i].active & 2)
            {
                Print(win, (const u8 *)box->mons[i].name, 46 + line * 12);
                line++;
            }
        if (!line) Print(win, sNoParty, 48);
        Print(win, sPartyHelp, 126);
    }
    else
    {
        if (area == SOUL_STARTER)
            StringCopy(buffer, sSoulText12);
        else
            GetMapName(buffer, area % 256, 0);
        Print(win, buffer, 32);
        Print(win, area >= 256 && area != SOUL_STARTER ? sSoulText13 : sSoulText14, 46);
        i = gPokemonStoragePtr->soul.state[area];
        if (i == SOUL_AVAILABLE && box->mons[area].state == SOUL_PENDING)
            Print(win, sSoulText15, 62);
        else
            Print(win, i == SOUL_AVAILABLE ? sSoulText16 : i == SOUL_PENDING ? sSoulText17 : i == SOUL_LINKED ? sSoulText18 : i == SOUL_DEAD ? sSoulText19 : sSoulText20, 62);
        if (box->mons[area].species)
        {
            end = StringCopy(buffer, (const u8 *)box->remoteTrainer);
            end = StringCopy(end, sSoulText21);
            StringCopy(end, (const u8 *)box->mons[area].name);
            Print(win, buffer, 78);
        }
        if (box->ended)
            Print(win, sSoulText22, 94);
        else
            Print(win, sSoulText23, 94);
        Print(win, sSoulText24, 110);
        Print(win, sSoulText11, 126);
    }
    if (box->reserved[0]) Print(win, sPartyRejected, 110);
    PutWindowTilemap(win);
    CopyWindowToVram(win, COPYWIN_FULL);
}

static void MenuTask(u8 taskId)
{
    struct Task *task = &gTasks[taskId];
    volatile struct SoulMailbox *box = &gSoulLinkMailbox;
    u16 sel = task->data[2], area, count;
    if (JOY_NEW(B_BUTTON))
    {
        ClearWindowTilemap(task->data[0]);
        CopyWindowToVram(task->data[0], COPYWIN_MAP);
        RemoveWindow(task->data[0]);
        UnlockPlayerFieldControls();
        DestroyTask(taskId);
        return;
    }
    if (!box->locked)
    {
        if (JOY_NEW(DPAD_UP)) task->data[2] = (sel + 19) % 20;
        if (JOY_NEW(DPAD_DOWN)) task->data[2] = (sel + 1) % 20;
        if (box->player == 0 && box->connection == 2 && JOY_NEW(DPAD_LEFT | DPAD_RIGHT))
        {
            if (sel < 14)
                SoulLink_SendSettings(box->rules ^ (1 << sel), box->seed, FALSE);
            else if (sel < 18)
            {
                u32 rules = box->rules & SOUL_START_OPTIONS ? box->rules : box->rules | SOUL_DEFAULT_OPTIONS;
                u8 shift = sel == 14 ? 14 : sel == 15 ? 16 : sel == 16 ? 17 : 18;
                u8 mask = sel == 14 ? 3 : sel == 17 ? 31 : 1;
                u8 count = sel == 14 ? 3 : sel == 17 ? 20 : 2;
                u8 value = (((rules >> shift) & mask) + (JOY_NEW(DPAD_RIGHT) ? 1 : count - 1)) % count;
                rules = (rules & ~((u32)mask << shift)) | ((u32)value << shift);
                SoulLink_SendSettings(rules, box->seed, FALSE);
            }
            else if (sel == 18)
                SoulLink_SendSettings(box->rules, box->seed + (JOY_NEW(DPAD_RIGHT) ? 1 : -1), FALSE);
        }
        if (sel == 19 && JOY_NEW(A_BUTTON) && box->connection == 2)
            SoulLink_SendSettings(box->rules, box->seed, TRUE);
    }
    else
    {
        if (JOY_NEW(L_BUTTON)) task->data[4] ^= 1;
        area = task->data[1];
        if (JOY_NEW(DPAD_LEFT)) area = (area + SOUL_AREAS-1) % SOUL_AREAS;
        if (JOY_NEW(DPAD_RIGHT)) area = (area + 1) % SOUL_AREAS;
        if (JOY_NEW(DPAD_UP | DPAD_DOWN))
            for (count = 0; count < SOUL_AREAS; count++)
            {
                area = (area + (JOY_NEW(DPAD_DOWN) ? 1 : SOUL_AREAS-1)) % SOUL_AREAS;
                if (gPokemonStoragePtr->soul.state[area] || box->mons[area].state)
                    break;
            }
        task->data[1] = area;
        if (box->connection == 2 && JOY_NEW(A_BUTTON)) SoulLink_SendParty(FALSE);
        if (box->connection == 2 && JOY_NEW(R_BUTTON)) SoulLink_SendParty(TRUE);
    }
    if (gMain.newKeys || ++task->data[3] >= 30)
    {
        task->data[3] = 0;
        Draw(taskId);
    }
}
