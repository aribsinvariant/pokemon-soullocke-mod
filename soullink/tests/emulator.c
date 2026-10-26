/* Headless ROM integration adapter, linked against libmgba for tests only. */
#include <mgba/core/core.h>
#include <mgba/core/log.h>
#include <mgba/core/scripting.h>
#include <mgba/core/timing.h>
#include <mgba/script/context.h>
#include <mgba/internal/arm/arm.h>
#include <mgba/internal/arm/isa-inlines.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static void quiet(struct mLogger *logger, int category, enum mLogLevel level, const char *format, va_list args) {}
static struct mLogger logger = {.log=quiet};
struct Harness { struct mCore *core; color_t pixels[240*160]; struct mScriptContext script; int scripted; };
struct Harness *sl_new(const char *rom) {
    mLogSetDefaultLogger(&logger);
    struct Harness *h = calloc(1, sizeof(*h));
    h->core = mCoreFind(rom);
    if (!h->core || !h->core->init(h->core)) return NULL;
    mCoreInitConfig(h->core, "soullink-test");
    mCoreConfigSetIntValue(&h->core->config, "skipBios", 1);
    mCoreLoadConfig(h->core);
    h->core->setVideoBuffer(h->core, h->pixels, 240);
    if (!mCoreLoadFile(h->core, rom)) return NULL;
    h->core->reset(h->core);
    return h;
}
void sl_free(struct Harness *h) { if (h->scripted) { mScriptContextDetachCore(&h->script); mScriptContextDeinit(&h->script); } h->core->deinit(h->core); free(h); }
void sl_run(struct Harness *h, unsigned count, unsigned keys) {
    h->core->setKeys(h->core, keys);
    while (count--) h->core->runFrame(h->core);
}
uint64_t sl_cycles(struct Harness *h) {
    return mTimingGlobalTime(h->core->timing);
}
unsigned sl_read(struct Harness *h, unsigned address, unsigned width) {
    if (width == 1) return h->core->busRead8(h->core,address);
    if (width == 2) return h->core->busRead16(h->core,address);
    return h->core->busRead32(h->core,address);
}
void sl_write(struct Harness *h, unsigned address, unsigned value, unsigned width) {
    if (width == 1) h->core->busWrite8(h->core,address,value);
    else if (width == 2) h->core->busWrite16(h->core,address,value);
    else h->core->busWrite32(h->core,address,value);
}
unsigned sl_call(struct Harness *h, unsigned address, unsigned *args, unsigned count) {
    struct ARMCore *cpu = h->core->cpu;
    struct ARMRegisterFile regs = cpu->regs;
    unsigned prefetch[2] = {cpu->prefetch[0], cpu->prefetch[1]};
    unsigned ime = sl_read(h,0x04000208,2);
    unsigned limit = 20000000, i;
    sl_write(h,0x04000208,0,2);
    ARMSetPrivilegeMode(cpu, MODE_SYSTEM);
    _ARMSetMode(cpu, MODE_THUMB);
    cpu->gprs[ARM_SP] = 0x03007B00;
    for (i=0; i<count; i++) {
        if (i<4) cpu->gprs[i] = args[i];
        else sl_write(h,cpu->gprs[ARM_SP]+(i-4)*4,args[i],4);
    }
    cpu->gprs[ARM_LR] = 0x0203FFF1;
    sl_write(h,0x0203FFF0,0xE7FE,2);
    cpu->gprs[ARM_PC] = address & ~1u;
    ThumbWritePC(cpu);
    while ((unsigned)cpu->gprs[ARM_PC] != 0x0203FFF2 && limit--) h->core->step(h->core);
    unsigned result = cpu->gprs[0];
    if (!limit) { fprintf(stderr,"ROM function timeout at %08x, pc=%08x\n",address,cpu->gprs[ARM_PC]); abort(); }
    _ARMSetMode(cpu, regs.cpsr.t);
    ARMSetPrivilegeMode(cpu, regs.cpsr.priv);
    cpu->regs = regs;
    memcpy(cpu->prefetch,prefetch,sizeof(prefetch));
    cpu->memory.setActiveRegion(cpu,cpu->gprs[ARM_PC]);
    sl_write(h,0x04000208,ime,2);
    return result;
}
void sl_image(struct Harness *h, const char *path) {
    FILE *f=fopen(path,"wb"); fprintf(f,"P6\n240 160\n255\n");
    for(unsigned i=0;i<240*160;i++) {
        unsigned value=h->pixels[i];
        unsigned char rgb[3]={value & 255,(value>>8)&255,(value>>16)&255};
        fwrite(rgb,1,3,f);
    }
    fclose(f);
}

static void script_log(struct mLogger *logger, int category, enum mLogLevel level, const char *format, va_list args) {
    vfprintf(stderr,format,args); fputc('\n',stderr);
}
static struct mLogger scriptLogger = {.log=script_log};
int sl_script(struct Harness *h, const char *path) {
    mScriptContextInit(&h->script);
    mScriptContextRegisterEngines(&h->script);
    mScriptContextAttachStdlib(&h->script);
    mScriptContextAttachSocket(&h->script);
    mScriptContextAttachCore(&h->script,h->core);
    mScriptContextAttachLogger(&h->script,&scriptLogger);
    h->scripted=1;
    if (!mScriptContextLoadFile(&h->script,path)) return 0;
    struct mScriptEngineContext *engine = HashTableLookup(&h->script.engines,"lua");
    if (!engine) return 0;
    int result = engine->run(engine);
    if (!result) fprintf(stderr,"Lua load error: %s\n",engine->getError(engine));
    return result;
}
void sl_tick(struct Harness *h) { mScriptContextTriggerCallback(&h->script,"frame"); }
