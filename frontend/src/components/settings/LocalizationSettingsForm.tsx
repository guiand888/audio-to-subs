import { useState } from "react"
import { Check, ChevronsUpDown } from "lucide-react"

import { cn } from "@/lib/utils"
import { listTimezones } from "@/lib/datetime"
import type { SettingsPatch } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command"

const TIMEZONE_GROUPS = listTimezones()

export interface LocalizationSettingsFormProps {
  formData: Partial<SettingsPatch>
  onChange: (updates: Partial<SettingsPatch>) => void
}

export function LocalizationSettingsForm({
  formData,
  onChange,
}: LocalizationSettingsFormProps) {
  const [open, setOpen] = useState(false)
  const selected = formData.timezone || "UTC"

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="timezone-picker">Display Timezone</Label>
        <p className="text-sm text-muted-foreground">
          Times across the UI (logs, history, jobs) are shown in this timezone.
        </p>
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              id="timezone-picker"
              variant="outline"
              role="combobox"
              aria-expanded={open}
              className="w-full justify-between font-normal"
            >
              {selected}
              <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
            <Command>
              <CommandInput placeholder="Search timezone…" />
              <CommandList>
                <CommandEmpty>No timezone found.</CommandEmpty>
                {TIMEZONE_GROUPS.map((group) => (
                  <CommandGroup key={group.region} heading={group.region}>
                    {group.zones.map((zone) => (
                      <CommandItem
                        key={zone}
                        value={zone}
                        onSelect={(value: string) => {
                          onChange({ timezone: value })
                          setOpen(false)
                        }}
                      >
                        <Check
                          className={cn(
                            "mr-2 h-4 w-4",
                            selected === zone ? "opacity-100" : "opacity-0",
                          )}
                        />
                        {zone}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                ))}
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
      </div>
    </div>
  )
}
