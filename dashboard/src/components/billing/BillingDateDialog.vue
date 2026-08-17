<script setup lang="ts">
import { Button, Dialog, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { errorToast, successToast } from '@/lib/toast'

// Pick the day of the month we take the money, the way a bank lets you pick an EMI
// date. Days, not a calendar: the choice is a day-of-month that repeats, and the
// whole set fits on one line, so there is nothing for a date picker to add.
//
// The two lines under the chips are the point of the dialog. A customer moving
// their payment day is entitled to know exactly how much of their billing moves
// with it — which is only the debit. The bill still arrives on the 1st and the due
// date does not shift, so choosing the 7th is not six extra days of credit.
const props = defineProps<{
	day: number
	choices: number[]
	collectionMode?: string | null
}>()
const emit = defineEmits<{ saved: [] }>()
const open = defineModel<boolean>('open', { default: false })
const { activeTeam } = useSession()

const selected = ref(props.day || 1)
// Re-seed on open rather than on mount: the dialog outlives a cancel, and a
// customer who backs out and returns must see what is actually saved, not what
// they abandoned.
watch(open, (isOpen) => {
	if (isOpen) selected.value = props.day || 1
})

const save = useCall<unknown, { team: string; day: number }>({
	url: method(API.setBillingDate),
	method: 'POST',
	immediate: false,
})

const dirty = computed(() => selected.value !== (props.day || 1))
// A team that pays each bill by hand has no automatic debit to move. The control is
// still theirs to set — the day is honoured the moment auto-pay is on — but saying
// nothing here would promise a change they would not see happen.
const inert = computed(() => props.collectionMode !== 'Auto Charge')

function ordinal(day: number): string {
	const suffix =
		day % 10 === 1 && day !== 11
			? 'st'
			: day % 10 === 2 && day !== 12
				? 'nd'
				: day % 10 === 3 && day !== 13
					? 'rd'
					: 'th'
	return `${day}${suffix}`
}

async function submit(): Promise<void> {
	try {
		await save.submit({ team: activeTeam.value!, day: selected.value })
		if (save.error) throw save.error
		successToast(`We'll charge you on the ${ordinal(selected.value)} of each month`)
		open.value = false
		emit('saved')
	} catch (e) {
		errorToast(e)
	}
}
</script>

<template>
	<Dialog v-model:open="open" title="Billing date">
		<template #default>
			<div class="space-y-4">
				<p class="text-p-base text-ink-gray-7">
					Which day of the month should we take payment?
				</p>

				<div class="flex flex-wrap gap-2">
					<Button
						v-for="choice in choices"
						:key="choice"
						:variant="choice === selected ? 'solid' : 'outline'"
						:label="String(choice)"
						class="w-10 tabular-nums"
						@click="selected = choice"
					/>
				</div>

				<div class="rounded-5 bg-surface-gray-1 p-3">
					<p class="text-p-sm text-ink-gray-7">
						Your bill still arrives on the 1st and its due date doesn't change —
						this only moves the day we charge you.
					</p>
					<p v-if="inert" class="mt-1.5 text-p-sm text-ink-gray-5">
						You pay these bills manually right now, so this takes effect when you
						switch on auto-pay.
					</p>
				</div>
			</div>
		</template>

		<template #actions>
			<div class="flex items-center justify-end gap-2">
				<Button label="Cancel" @click="open = false" />
				<Button
					variant="solid"
					label="Save"
					:disabled="!dirty"
					:loading="save.loading"
					@click="submit"
				/>
			</div>
		</template>
	</Dialog>
</template>
