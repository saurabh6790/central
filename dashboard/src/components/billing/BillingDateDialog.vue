<script setup lang="ts">
import { Button, Dialog, useCall } from 'frappe-ui'
import { computed, ref, watch } from 'vue'
import { API, method } from '@/api/methods'
import { useSession } from '@/composables/useSession'
import { ordinalDay } from '@/lib/date'
import { errorToast, successToast } from '@/lib/toast'

// Pick the day of the month we take the money, the way a bank lets you pick an EMI
// date. Days, not a calendar: the choice is a day of the month that repeats, and
// the whole set fits on one line, so a date picker would add nothing.
//
// The lines under the chips are the point of the dialog. Someone moving their
// payment day needs to know how much of their billing moves with it, which is only
// the debit. The bill still arrives on the 1st and the due date stays put, so
// picking the 7th does not buy six extra days.
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
// A team that pays each bill by hand has no automatic debit to move. The day is
// still theirs to set, and it counts the moment auto-pay is on, but saying nothing
// here would promise them a change they would never see happen.
const inert = computed(() => props.collectionMode !== 'Auto Charge')

async function submit(): Promise<void> {
	try {
		await save.submit({ team: activeTeam.value!, day: selected.value })
		if (save.error) throw save.error
		successToast(
			`We'll take payment on the ${ordinalDay(selected.value)} of each month`,
		)
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
					Which day of the month suits you for payment?
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
						Your bill still arrives on the 1st and it's due on the same date as
						before. All that changes is the day we take the money.
					</p>
					<p v-if="inert" class="mt-1.5 text-p-sm text-ink-gray-5">
						You're paying these bills yourself at the moment, so we won't charge
						you on this date until you turn on auto-pay.
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
