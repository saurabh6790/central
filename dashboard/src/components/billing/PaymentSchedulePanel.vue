<script setup lang="ts">
import { Button, LoadingText, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import BillingDateDialog from '@/components/billing/BillingDateDialog.vue'
import SidePanel from '@/components/common/SidePanel.vue'
import { useBillingOverview } from '@/composables/useBillingOverview'
import { useSession } from '@/composables/useSession'
import { formatDate, money } from '@/lib/format'
import { shortDate } from '@/lib/date'
import type { PaymentSchedule } from '@/types/billing'

// The tray behind "Next payment": the debit itself, the 24-hour pre-debit notices
// we sent (the RBI record — written on every notice already, ADR 0005, and the
// customer's copy of it), and what happens if the bill goes unpaid.
//
// The escalation ladder is published up front deliberately. Dunning is the part of
// billing customers fear most, and it is far less frightening stated as a dated
// process with "nothing is deleted" attached than discovered one failed retry at a
// time. Loaded on open — nobody needs a dunning ladder on first paint.
const open = defineModel<boolean>('open', { default: false })
const { activeTeam } = useSession()

const schedule = useCall<PaymentSchedule, { team: string }>({
	url: method(API.paymentSchedule),
	params: () => ({ team: activeTeam.value! }),
	immediate: false,
})
watch(open, (isOpen) => {
	if (isOpen && activeTeam.value) schedule.reload()
})

// Whether this team may name the day it is charged. False for almost everyone,
// because the feature is off site-wide or ops has not granted it, and then the date
// is stated exactly as it was before with nothing to press. Read from the shared
// overview so this tray and the card behind it can never disagree.
const { billingDate, reloadBillingDate } = useBillingOverview()
const picking = ref(false)
const canPick = computed(() => Boolean(billingDate.data?.available))

// The date is stated on this row, so it is changed on this row too. Sending someone
// off to a settings page to edit a number they are looking at is the long way round.
function onSaved(): void {
	reloadBillingDate()
	schedule.reload()
}

const loading = computed(() => schedule.loading && !schedule.data)
const data = computed(() => schedule.data)
const currency = computed(() => data.value?.currency ?? 'INR')
const amount = computed(() => Number(data.value?.amount ?? 0))
</script>

<template>
	<SidePanel v-model:open="open" title="Payment schedule">
		<div v-if="loading" class="space-y-3 p-4">
			<LoadingText :lines="5" />
		</div>

		<template v-else>
			<!-- What we intend to do -->
			<div class="border-b border-outline-gray-2 p-4">
				<div class="flex items-baseline justify-between gap-3">
					<span class="text-p-sm text-ink-gray-5">Amount due</span>
					<span class="text-base-medium tabular-nums text-ink-gray-9">
						{{ money(amount, currency) }}
					</span>
				</div>
				<div class="mt-1.5 flex items-baseline justify-between gap-3">
					<span class="text-p-sm text-ink-gray-5">We'll charge on</span>
					<span class="flex items-baseline gap-1.5">
						<span class="text-sm-medium text-ink-gray-8">
							{{ shortDate(data?.charge_on) || '—' }}
						</span>
						<Button
							v-if="canPick"
							variant="subtle"
							size="sm"
							icon-left="lucide-calendar"
							label="Change"
							@click="picking = true"
						/>
					</span>
				</div>
				<div
					v-if="data?.method?.label"
					class="mt-1.5 flex items-baseline justify-between gap-3"
				>
					<span class="text-p-sm text-ink-gray-5">From</span>
					<span class="text-sm-medium text-ink-gray-8">
						{{ data.method.label }}
					</span>
				</div>
				<div
					v-if="data?.method?.ceiling"
					class="mt-1.5 flex items-baseline justify-between gap-3"
				>
					<span class="text-p-sm text-ink-gray-5">Auto-debit limit</span>
					<span class="text-sm-medium tabular-nums text-ink-gray-8">
						{{ money(data.method.ceiling, currency) }}
					</span>
				</div>
			</div>

			<!-- Anything that stops it, and what to do -->
			<div v-if="data?.blockers?.length" class="border-b border-outline-gray-2 p-4">
				<div
					v-for="b in data.blockers"
					:key="b.code"
					class="rounded-5 border border-outline-amber-2 bg-surface-amber-1 p-3"
				>
					<p class="text-base-medium text-ink-gray-9">{{ b.title }}</p>
					<p v-if="b.fix" class="mt-0.5 text-p-sm text-ink-gray-7">{{ b.fix }}</p>
				</div>
			</div>

			<!-- The compliance record, made the customer's -->
			<div v-if="data?.notices?.length" class="border-b border-outline-gray-2 p-4">
				<p class="mb-2 text-p-sm text-ink-gray-5">
					Advance notices we sent you before debiting
				</p>
				<ul class="divide-y divide-outline-gray-1">
					<li
						v-for="(notice, idx) in data.notices"
						:key="idx"
						class="flex items-baseline justify-between gap-3 py-2"
					>
						<span class="min-w-0 truncate text-p-sm text-ink-gray-7">
							{{ notice.subject || notice.invoice || 'Pre-debit notice' }}
						</span>
						<span class="shrink-0 text-p-sm text-ink-gray-5">
							{{ formatDate(notice.sent_at) }}
						</span>
					</li>
				</ul>
			</div>

			<!-- Published up front, not discovered one retry at a time -->
			<div v-if="data?.if_unpaid?.length" class="p-4">
				<p class="mb-2 text-p-sm text-ink-gray-5">If this goes unpaid</p>
				<ul class="space-y-2">
					<li
						v-for="(stage, idx) in data.if_unpaid"
						:key="idx"
						class="flex items-baseline justify-between gap-3"
					>
						<span class="text-p-sm text-ink-gray-7">{{ stage.stage }}</span>
						<span class="shrink-0 text-p-sm tabular-nums text-ink-gray-5">
							{{ shortDate(stage.date) }}
						</span>
					</li>
				</ul>
				<p class="mt-3 text-p-sm text-ink-gray-5">
					Servers stop at suspension. Nothing is deleted, and you can start them
					again once the bill is settled.
				</p>
			</div>
		</template>
	</SidePanel>

	<BillingDateDialog
		v-model:open="picking"
		:day="billingDate.data?.day ?? 0"
		:choices="billingDate.data?.choices ?? []"
		:collection-mode="data?.collection_mode"
		@saved="onSaved"
	/>
</template>
