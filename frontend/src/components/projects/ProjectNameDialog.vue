<script>
import {
  computed,
  defineComponent,
  nextTick,
  onMounted,
  ref,
  toRef,
  watch,
} from 'vue'

export function createProjectNameDialogController({
  initialTitle = '',
  pending = ref(false),
  emit,
  focusInput = () => {},
}) {
  const title = ref(initialTitle)
  const error = ref('')
  const submitted = ref(false)
  const disabled = computed(() => Boolean(pending.value || submitted.value))

  watch(pending, (next, previous) => {
    if (previous && !next) submitted.value = false
  })

  function submit() {
    if (disabled.value) return false
    const normalizedTitle = String(title.value || '').trim()
    if (!normalizedTitle) {
      error.value = '请输入项目名称'
      void nextTick(focusInput)
      return false
    }
    error.value = ''
    submitted.value = true
    emit('submit', { title: normalizedTitle })
    return true
  }

  function handleKeydown(event) {
    if (event?.key !== 'Enter') return false
    event.preventDefault?.()
    return submit()
  }

  return {
    title,
    error,
    disabled,
    submit,
    handleKeydown,
  }
}

export default defineComponent({
  name: 'ProjectNameDialog',
  props: {
    title: {
      type: String,
      required: true,
    },
    initialTitle: {
      type: String,
      default: '',
    },
    pending: {
      type: Boolean,
      default: false,
    },
    serverError: {
      type: String,
      default: '',
    },
    submitLabel: {
      type: String,
      default: '保存',
    },
    onCancel: {
      type: Function,
      default: () => {},
    },
  },
  emits: ['submit'],
  setup(props, { emit }) {
    const input = ref(null)
    const controller = createProjectNameDialogController({
      initialTitle: props.initialTitle,
      pending: toRef(props, 'pending'),
      emit,
      focusInput: () => input.value?.focus(),
    })
    const visibleError = computed(() => controller.error.value || props.serverError)
    const dialogTitle = computed(() => props.title)

    function cancel() {
      if (!controller.disabled.value) props.onCancel()
    }

    function handleDialogKeydown(event) {
      if (event.key !== 'Escape') return
      event.preventDefault()
      cancel()
    }

    onMounted(() => {
      void nextTick(() => input.value?.focus())
    })

    return {
      ...controller,
      input,
      visibleError,
      dialogTitle,
      cancel,
      handleDialogKeydown,
    }
  },
})
</script>

<template>
  <div class="name-dialog-backdrop" @keydown="handleDialogKeydown">
    <section
      class="name-dialog"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="`${$attrs.id || 'project-name'}-title`"
    >
      <header>
        <p>PROJECT IDENTITY</p>
        <h2 :id="`${$attrs.id || 'project-name'}-title`">{{ dialogTitle }}</h2>
      </header>
      <form @submit.prevent="submit">
        <label for="project-name-input">项目名称</label>
        <input
          id="project-name-input"
          ref="input"
          v-model="title"
          name="projectName"
          type="text"
          maxlength="200"
          autocomplete="off"
          aria-describedby="project-name-error"
          :aria-invalid="Boolean(visibleError)"
          :disabled="pending"
          @input="error = ''"
          @keydown="handleKeydown"
        >
        <p id="project-name-error" class="name-dialog__error" aria-live="polite">
          {{ visibleError }}
        </p>
        <footer>
          <button type="button" class="name-dialog__cancel" :disabled="pending" @click="cancel">
            取消
          </button>
          <button type="submit" class="name-dialog__submit" :disabled="disabled">
            {{ pending ? '正在保存…' : submitLabel }}
          </button>
        </footer>
      </form>
    </section>
  </div>
</template>

<style scoped>
.name-dialog-backdrop {
  position: fixed;
  z-index: 1200;
  inset: 0;
  display: grid;
  padding: 24px;
  place-items: center;
  background: rgba(47, 40, 33, .26);
  backdrop-filter: blur(2px);
}

.name-dialog {
  width: min(470px, 100%);
  padding: 28px;
  border: 1px solid var(--nc-border, #d8cbb7);
  border-radius: 12px;
  color: var(--nc-ink, #302a23);
  background: var(--nc-paper, #fffdf8);
  box-shadow: 0 28px 80px rgba(38, 28, 19, .22);
}

.name-dialog header {
  padding-bottom: 18px;
  border-bottom: 1px solid #e1d7c7;
}

.name-dialog header p {
  margin: 0;
  color: var(--nc-vermilion, #8f3d32);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .16em;
}

.name-dialog h2 {
  margin: 8px 0 0;
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 26px;
  font-weight: 600;
}

.name-dialog form {
  padding-top: 22px;
}

.name-dialog label {
  display: block;
  margin-bottom: 8px;
  font-size: 13px;
  font-weight: 700;
}

.name-dialog input {
  width: 100%;
  height: 44px;
  padding: 0 13px;
  border: 1px solid #cfc1ad;
  border-radius: 7px;
  color: var(--nc-ink, #302a23);
  background: #fffefa;
  font: inherit;
}

.name-dialog input:focus-visible {
  border-color: var(--nc-vermilion, #8f3d32);
  outline: 3px solid rgba(143, 61, 50, .18);
}

.name-dialog__error {
  min-height: 20px;
  margin: 7px 0 0;
  color: #a22f2b;
  font-size: 12px;
}

.name-dialog footer {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
}

.name-dialog button {
  min-height: 38px;
  padding: 0 17px;
  border: 0;
  border-radius: 7px;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}

.name-dialog__cancel {
  color: var(--nc-ink, #302a23);
  background: #eee7dc;
}

.name-dialog__submit {
  color: #fffaf0;
  background: var(--nc-vermilion, #8f3d32);
}

.name-dialog button:focus-visible {
  outline: 3px solid rgba(143, 61, 50, .25);
  outline-offset: 2px;
}

.name-dialog button:disabled {
  cursor: wait;
  opacity: .6;
}
</style>
