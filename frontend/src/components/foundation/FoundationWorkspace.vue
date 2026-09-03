<script setup>
// This shell omits only its own actions slot when the caller's shared readOnly state is true.
defineProps({
  title: { type: String, required: true },
  purpose: { type: String, required: true },
  statusLabel: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
})
</script>

<template>
  <section class="foundation-workspace" :class="{ 'foundation-workspace--readonly': readOnly }">
    <header class="foundation-workspace__header">
      <p class="foundation-workspace__kicker">AUTHORING FOUNDATION</p>
      <div>
        <h1>{{ title }}</h1>
        <p class="foundation-workspace__purpose">{{ purpose }}</p>
      </div>
      <p v-if="statusLabel" class="foundation-workspace__header-status">{{ statusLabel }}</p>
    </header>

    <div class="foundation-workspace__grid">
      <aside class="foundation-workspace__index" aria-label="文档目录">
        <slot name="index" />
      </aside>
      <aside class="foundation-workspace__status" aria-label="文档状态与操作">
        <slot name="status" />
        <div v-if="!readOnly && $slots.actions" class="foundation-workspace__actions">
          <slot name="actions" />
        </div>
      </aside>
      <section class="foundation-workspace__document" aria-label="创作正文">
        <slot name="document" />
      </section>
    </div>
  </section>
</template>

<style scoped>
.foundation-workspace {
  --paper:var(--nc-paper);
  --ink:var(--nc-ink);
  --muted:var(--nc-muted);
  --rule:var(--nc-border);
  --cinnabar:var(--nc-vermilion);
  --jade:var(--nc-jade);
  min-width:0;
  padding:clamp(22px,4vw,52px);
  overflow-wrap:anywhere;
  color:var(--nc-ink);
  background:var(--nc-canvas);
}
.foundation-workspace__header { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px 28px; width:min(1320px,100%); min-width:0; margin:0 auto 20px; padding:0 0 18px; border-bottom:2px solid var(--nc-vermilion); }
.foundation-workspace__kicker { grid-column:1 / -1; margin:0; color:var(--nc-vermilion); font:700 10px Georgia,'Noto Serif SC',serif; letter-spacing:.18em; }
.foundation-workspace h1 { margin:0; font:600 clamp(32px,5vw,54px)/1.12 Georgia,'Noto Serif SC',serif; }
.foundation-workspace__purpose { max-width:48rem; margin:10px 0 0; color:var(--nc-muted); font:15px/1.75 Georgia,'Noto Serif SC',serif; }
.foundation-workspace__header-status { align-self:end; margin:0; color:var(--nc-vermilion); font:700 12px Georgia,'Noto Serif SC',serif; letter-spacing:.08em; text-align:right; }
.foundation-workspace__grid { display:grid; grid-template-areas:'index document status'; grid-template-columns:minmax(168px,.72fr) minmax(0,2.5fr) minmax(196px,.86fr); gap:18px; width:min(1320px,100%); min-width:0; margin:auto; align-items:start; }
.foundation-workspace__index,.foundation-workspace__document,.foundation-workspace__status { min-width:0; }
.foundation-workspace__index { grid-area:index; }.foundation-workspace__status { grid-area:status; position:sticky; top:18px; align-self:start; }.foundation-workspace__index,.foundation-workspace__status { border-top:1px solid var(--nc-border); }
.foundation-workspace__document { grid-area:document; min-height:clamp(420px,68vh,760px); border:1px solid var(--nc-border); background:repeating-linear-gradient(0deg,var(--nc-paper),var(--nc-paper) 29px,color-mix(in srgb,var(--nc-paper) 94%,var(--nc-canvas)) 30px); box-shadow:0 24px 64px color-mix(in srgb,var(--nc-ink) 9%,transparent); }
.foundation-workspace__actions { display:grid; gap:8px; margin-top:16px; padding-top:16px; border-top:1px solid var(--nc-border); }
@media (max-width:980px) { .foundation-workspace__grid { grid-template-columns:minmax(142px,.7fr) minmax(0,2fr) minmax(164px,.78fr); gap:12px; } }
@media (max-width:760px) { .foundation-workspace { padding:18px 12px 30px; } .foundation-workspace__header { grid-template-columns:1fr; } .foundation-workspace__header-status { justify-self:start; text-align:left; } .foundation-workspace__grid { grid-template-areas:'index' 'status' 'document'; grid-template-columns:minmax(0,1fr); } .foundation-workspace__status { position:static; } .foundation-workspace__document { min-height:0; } }
@media (prefers-reduced-motion:reduce) { .foundation-workspace *, .foundation-workspace *::before, .foundation-workspace *::after { scroll-behavior:auto !important; transition:none !important; animation:none !important; } }
</style>
