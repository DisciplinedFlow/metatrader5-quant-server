<script setup>
import { ref, reactive, computed } from 'vue'
import { useToast } from '@/composables/useToast'
import api from '@/services/api'

const props = defineProps({
  domain: { type: String, default: 'FOREX' },
})

const emit = defineEmits(['saved', 'cancel'])

const toast = useToast()
const saving = ref(false)

const PLATFORM_CONFIG = {
  FOREX: {
    pairs: ['NG', 'BRN', 'WTI', 'XAGUSD', 'XAUUSD', 'XAUEUR', 'EURUSD', 'EURGBP', 'USDJPY', 'USDCAD', 'USDCHF', 'AUDUSD', 'NZDUSD'],
    timeframes: ['M1', 'M5', 'M15', 'H1', 'H4', 'D1'],
    pairLabel: 'Trading Pairs',
    longLabel: 'Entry Rules - Long',
    shortLabel: 'Entry Rules - Short',
  },
}

const platformConfig = computed(() => PLATFORM_CONFIG[props.domain] || PLATFORM_CONFIG.FOREX)
const ALL_PAIRS = computed(() => platformConfig.value.pairs)
const TIMEFRAMES = computed(() => platformConfig.value.timeframes)
const INDICATOR_TYPES = [
  { value: 'EMA_CROSSOVER', label: 'EMA Crossover', defaults: { fast: 9, slow: 21 } },
  { value: 'RSI', label: 'RSI', defaults: { period: 14 } },
  { value: 'BOLLINGER_BANDS', label: 'Bollinger Bands', defaults: { window: 20, num_std_dev: 2 } },
]
const OPERATORS = ['eq', 'gt', 'gte', 'lt', 'lte']

const form = reactive({
  name: '',
  description: '',
  timeframe: 'M5',
  pairs: ['EURUSD', 'XAUUSD'],
  indicators: [],
  longRules: [],
  shortRules: [],
  exitType: 'ATR_BASED',
  exitParams: { atr_period: 14, sl_multiplier: 1.5, tp_multiplier: 2.0, sl_pct: 0.5, tp_pct: 0.5 },
  min_win_rate: 0.55,
})

function addIndicator() {
  const type = INDICATOR_TYPES[0]
  form.indicators.push({ type: type.value, params: { ...type.defaults } })
}

function removeIndicator(idx) {
  form.indicators.splice(idx, 1)
}

function addRule(side) {
  const rules = side === 'long' ? form.longRules : form.shortRules
  rules.push({ indicator: form.indicators.length ? form.indicators[0].type : '', condition: 'eq', value: '' })
}

function removeRule(side, idx) {
  const rules = side === 'long' ? form.longRules : form.shortRules
  rules.splice(idx, 1)
}

function getIndicatorDefaults(typeValue) {
  return INDICATOR_TYPES.find(t => t.value === typeValue)?.defaults || {}
}

function onIndicatorTypeChange(idx, newType) {
  form.indicators[idx].type = newType
  form.indicators[idx].params = { ...getIndicatorDefaults(newType) }
}

function togglePair(pair) {
  const idx = form.pairs.indexOf(pair)
  if (idx >= 0) form.pairs.splice(idx, 1)
  else form.pairs.push(pair)
}

async function save() {
  if (!form.name.trim()) { toast.error('Name is required'); return }
  if (!form.pairs.length) { toast.error('Select at least one pair'); return }

  saving.value = true
  try {
    const definition = {
      timeframe: form.timeframe,
      pairs: form.pairs,
      indicators: form.indicators,
      entry_rules: {
        long: form.longRules,
        short: form.shortRules,
      },
      exit_rules: {
        type: form.exitType,
        params: form.exitType === 'ATR_BASED'
          ? { atr_period: form.exitParams.atr_period, sl_multiplier: form.exitParams.sl_multiplier, tp_multiplier: form.exitParams.tp_multiplier }
          : { sl_pct: form.exitParams.sl_pct, tp_pct: form.exitParams.tp_pct },
      },
      min_win_rate: form.min_win_rate,
    }

    await api.createCustomStrategy({
      name: form.name,
      description: form.description,
      definition,
      domain: props.domain,
    })
    toast.success('Strategy saved')
    emit('saved')
  } catch (err) {
    toast.error(`Save failed: ${err.message}`)
  }
  saving.value = false
}
</script>

<template>
  <article>
    <header><strong>New Custom Strategy</strong></header>

    <!-- Name & Description -->
    <label>
      Name
      <input v-model="form.name" type="text" placeholder="My Strategy" required />
    </label>
    <label>
      Description
      <textarea v-model="form.description" rows="2" placeholder="Optional description"></textarea>
    </label>

    <!-- Timeframe -->
    <label>
      Timeframe
      <select v-model="form.timeframe">
        <option v-for="tf in TIMEFRAMES" :key="tf" :value="tf">{{ tf }}</option>
      </select>
    </label>

    <!-- Pairs -->
    <fieldset>
      <legend>{{ platformConfig.pairLabel }}</legend>
      <div style="display: flex; flex-wrap: wrap; gap: 0.5rem;">
        <label v-for="pair in ALL_PAIRS" :key="pair" style="display: inline-flex; align-items: center; gap: 0.25rem; min-width: 6rem;">
          <input type="checkbox" :checked="form.pairs.includes(pair)" @change="togglePair(pair)" />
          {{ pair }}
        </label>
      </div>
    </fieldset>

    <!-- Indicators -->
    <fieldset>
      <legend>Indicators</legend>
      <div v-for="(ind, idx) in form.indicators" :key="idx" style="margin-bottom: 0.75rem; padding: 0.5rem; border: 1px solid var(--tp-border); border-radius: 4px;">
        <div class="grid" style="align-items: end;">
          <label>
            Type
            <select :value="ind.type" @change="onIndicatorTypeChange(idx, $event.target.value)">
              <option v-for="t in INDICATOR_TYPES" :key="t.value" :value="t.value">{{ t.label }}</option>
            </select>
          </label>
          <div v-if="ind.type === 'EMA_CROSSOVER'" class="grid">
            <label>Fast <input v-model.number="ind.params.fast" type="number" min="1" /></label>
            <label>Slow <input v-model.number="ind.params.slow" type="number" min="1" /></label>
          </div>
          <div v-else-if="ind.type === 'RSI'">
            <label>Period <input v-model.number="ind.params.period" type="number" min="1" /></label>
          </div>
          <div v-else-if="ind.type === 'BOLLINGER_BANDS'" class="grid">
            <label>Window <input v-model.number="ind.params.window" type="number" min="1" /></label>
            <label>Std Dev <input v-model.number="ind.params.num_std_dev" type="number" min="0.1" step="0.1" /></label>
          </div>
          <button class="outline secondary" style="width: auto;" @click="removeIndicator(idx)">Remove</button>
        </div>
      </div>
      <button class="outline" style="width: auto;" @click="addIndicator">+ Add Indicator</button>
    </fieldset>

    <!-- Entry Rules -->
    <fieldset>
      <legend>{{ platformConfig.longLabel }}</legend>
      <div v-for="(rule, idx) in form.longRules" :key="'l'+idx" class="grid" style="align-items: end;">
        <label>
          Indicator
          <select v-model="rule.indicator">
            <option v-for="ind in form.indicators" :key="ind.type" :value="ind.type">{{ ind.type }}</option>
          </select>
        </label>
        <label>
          Condition
          <select v-model="rule.condition">
            <option v-for="op in OPERATORS" :key="op" :value="op">{{ op }}</option>
          </select>
        </label>
        <label>
          Value
          <input v-model="rule.value" type="text" placeholder="e.g. bull_cross or 30" />
        </label>
        <button class="outline secondary" style="width: auto;" @click="removeRule('long', idx)">X</button>
      </div>
      <button class="outline" style="width: auto;" @click="addRule('long')">+ Add Long Rule</button>
    </fieldset>

    <fieldset>
      <legend>{{ platformConfig.shortLabel }}</legend>
      <div v-for="(rule, idx) in form.shortRules" :key="'s'+idx" class="grid" style="align-items: end;">
        <label>
          Indicator
          <select v-model="rule.indicator">
            <option v-for="ind in form.indicators" :key="ind.type" :value="ind.type">{{ ind.type }}</option>
          </select>
        </label>
        <label>
          Condition
          <select v-model="rule.condition">
            <option v-for="op in OPERATORS" :key="op" :value="op">{{ op }}</option>
          </select>
        </label>
        <label>
          Value
          <input v-model="rule.value" type="text" placeholder="e.g. bear_cross or 70" />
        </label>
        <button class="outline secondary" style="width: auto;" @click="removeRule('short', idx)">X</button>
      </div>
      <button class="outline" style="width: auto;" @click="addRule('short')">+ Add Short Rule</button>
    </fieldset>

    <!-- Exit Rules -->
    <fieldset>
      <legend>Exit Rules</legend>
      <div class="grid">
        <label>
          <input type="radio" v-model="form.exitType" value="ATR_BASED" /> ATR-Based
        </label>
        <label>
          <input type="radio" v-model="form.exitType" value="PERCENTAGE" /> Percentage-Based
        </label>
      </div>
      <div v-if="form.exitType === 'ATR_BASED'" class="grid">
        <label>ATR Period <input v-model.number="form.exitParams.atr_period" type="number" min="1" /></label>
        <label>SL Multiplier <input v-model.number="form.exitParams.sl_multiplier" type="number" min="0.1" step="0.1" /></label>
        <label>TP Multiplier <input v-model.number="form.exitParams.tp_multiplier" type="number" min="0.1" step="0.1" /></label>
      </div>
      <div v-else class="grid">
        <label>SL % <input v-model.number="form.exitParams.sl_pct" type="number" min="0.01" step="0.01" /></label>
        <label>TP % <input v-model.number="form.exitParams.tp_pct" type="number" min="0.01" step="0.01" /></label>
      </div>
    </fieldset>

    <!-- Min Win Rate -->
    <label>
      Min Win Rate
      <input v-model.number="form.min_win_rate" type="number" min="0" max="1" step="0.01" />
    </label>

    <!-- Actions -->
    <footer>
      <button class="outline secondary" @click="emit('cancel')">Cancel</button>
      <button :aria-busy="saving" @click="save">Save Strategy</button>
    </footer>
  </article>
</template>
