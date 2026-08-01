import assert from 'node:assert/strict'
import test from 'node:test'

import {
  capturePlainTextInput,
  capturePlainTextRange,
  locatePlainTextRange,
  scalarRangeToCodeUnits,
} from '../../src/utils/plainTextRange.js'

test('captures input text and Unicode selection from one event target, not stale props', () => {
  const stalePropsText = '甲乙'
  const target = {
    value: '😀甲乙',
    selectionStart: 2,
    selectionEnd: 2,
  }

  assert.notEqual(target.value, stalePropsText)
  assert.deepEqual(capturePlainTextInput(target), {
    value: '😀甲乙',
    selection: {
      startOffset: 1,
      endOffset: 1,
      selectedText: '',
    },
  })
})

test('captures a long pasted input without dropping its value or selection', () => {
  const pasted = `${'甲'.repeat(512)}😀${'乙'.repeat(512)}`
  const target = {
    value: pasted,
    selectionStart: pasted.length,
    selectionEnd: pasted.length,
  }

  assert.deepEqual(capturePlainTextInput(target), {
    value: pasted,
    selection: {
      startOffset: 1025,
      endOffset: 1025,
      selectedText: '',
    },
  })
})

test('converts textarea UTF-16 selection through Chinese, astral text, and a newline to scalar offsets', () => {
  const text = '甲😀乙\n丙'

  assert.deepEqual(capturePlainTextRange(text, 1, 4), {
    startOffset: 1,
    endOffset: 3,
    selectedText: '😀乙',
  })
  assert.deepEqual(scalarRangeToCodeUnits(text, 1, 3), {
    selectionStart: 1,
    selectionEnd: 4,
  })
})

test('preserves combining characters without normalization', () => {
  const text = 'e\u0301😀'

  assert.deepEqual(capturePlainTextRange(text, 0, 2), {
    startOffset: 0,
    endOffset: 2,
    selectedText: 'e\u0301',
  })
  assert.deepEqual(scalarRangeToCodeUnits(text, 0, 2), {
    selectionStart: 0,
    selectionEnd: 2,
  })
})

test('captures an empty selection at a scalar boundary', () => {
  assert.deepEqual(capturePlainTextRange('甲😀乙', 3, 3), {
    startOffset: 2,
    endOffset: 2,
    selectedText: '',
  })
})

test('rejects invalid UTF-16 and scalar ranges instead of clamping them', () => {
  const text = '😀乙'

  for (const [start, end] of [
    [-1, 0],
    [2, 1],
    [0, 4],
    [1, 2],
  ]) {
    assert.throws(() => capturePlainTextRange(text, start, end), RangeError)
  }
  assert.throws(() => capturePlainTextRange(text, 0.5, 2), TypeError)
  for (const [start, end] of [
    [-1, 0],
    [2, 1],
    [0, 3],
  ]) {
    assert.throws(() => scalarRangeToCodeUnits(text, start, end), RangeError)
  }
  assert.throws(() => scalarRangeToCodeUnits(text, 0, 1.5), TypeError)
})

test('rejects every unpaired surrogate before range conversion or textarea side effects', () => {
  for (const text of ['\uD800', '\uDC00', '甲\uD800乙', '甲\uDC00乙']) {
    const calls = []
    const textarea = {
      value: text,
      focus() {
        calls.push('focus')
      },
      setSelectionRange(start, end) {
        calls.push(['setSelectionRange', start, end])
      },
    }

    assert.throws(() => capturePlainTextRange(text, 0, 1), RangeError)
    assert.throws(() => capturePlainTextInput({
      value: text,
      selectionStart: 0,
      selectionEnd: 1,
    }), RangeError)
    assert.throws(() => scalarRangeToCodeUnits(text, 0, 1), RangeError)
    assert.throws(() => locatePlainTextRange(textarea, text, 0, 1), RangeError)
    assert.deepEqual(calls, [])
  }
})

test('treats a legal surrogate pair as one scalar', () => {
  const text = '\uD83D\uDE00'

  assert.deepEqual(capturePlainTextRange(text, 0, 2), {
    startOffset: 0,
    endOffset: 1,
    selectedText: text,
  })
  assert.deepEqual(scalarRangeToCodeUnits(text, 0, 1), {
    selectionStart: 0,
    selectionEnd: 2,
  })
})

test('locates scalar offsets only after textarea text validation', () => {
  const text = '甲😀乙\n丙'
  const calls = []
  const textarea = {
    value: text,
    focus() {
      calls.push('focus')
    },
    setSelectionRange(start, end) {
      calls.push(['setSelectionRange', start, end])
    },
  }

  assert.deepEqual(locatePlainTextRange(textarea, text, 1, 3), {
    selectionStart: 1,
    selectionEnd: 4,
  })
  assert.deepEqual(calls, ['focus', ['setSelectionRange', 1, 4]])
})

test('does not search a stale textarea value or focus it', () => {
  const text = '甲😀乙'
  const calls = []
  const textarea = {
    value: `前缀${text}`,
    focus() {
      calls.push('focus')
    },
    setSelectionRange(start, end) {
      calls.push(['setSelectionRange', start, end])
    },
  }

  assert.throws(() => locatePlainTextRange(textarea, text, 1, 2), RangeError)
  assert.deepEqual(calls, [])
})

test('rejects textarea type and capability defects before checking its value', () => {
  const text = '甲😀乙'

  for (const textarea of [
    null,
    {},
    { value: text },
    { value: text, focus() {} },
    { value: text, setSelectionRange() {} },
  ]) {
    assert.throws(() => locatePlainTextRange(textarea, text, 0, 1), TypeError)
  }
})

test('does not focus textarea when locate offsets are invalid', () => {
  const text = '甲😀乙'
  const calls = []
  const textarea = {
    value: text,
    focus() {
      calls.push('focus')
    },
    setSelectionRange(start, end) {
      calls.push(['setSelectionRange', start, end])
    },
  }

  assert.throws(() => locatePlainTextRange(textarea, text, 2, 1), RangeError)
  assert.deepEqual(calls, [])
})

test('rechecks textarea value after focus before setting its selection', () => {
  const text = '甲😀乙'
  const calls = []
  const textarea = {
    value: text,
    focus() {
      calls.push('focus')
      this.value = '焦点事件改变了文本'
    },
    setSelectionRange(start, end) {
      calls.push(['setSelectionRange', start, end])
    },
  }

  assert.throws(() => locatePlainTextRange(textarea, text, 1, 2), RangeError)
  assert.deepEqual(calls, ['focus'])
})

test('locates empty scalar ranges and rejects reversed ranges without side effects', () => {
  const text = '甲😀乙'
  const calls = []
  const textarea = {
    value: text,
    focus() {
      calls.push('focus')
    },
    setSelectionRange(start, end) {
      calls.push(['setSelectionRange', start, end])
    },
  }

  assert.deepEqual(locatePlainTextRange(textarea, text, 2, 2), {
    selectionStart: 3,
    selectionEnd: 3,
  })
  assert.deepEqual(calls, ['focus', ['setSelectionRange', 3, 3]])
  calls.length = 0
  assert.throws(() => locatePlainTextRange(textarea, text, 2, 1), RangeError)
  assert.deepEqual(calls, [])
})
