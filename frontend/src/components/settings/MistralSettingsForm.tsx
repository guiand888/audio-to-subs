import { Check } from "lucide-react"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Badge } from "@/components/ui/badge"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectContent,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import type { SettingsPatch } from "@/lib/types"

const MISTRAL_MODELS = [
  {
    value: "voxtral-mini-2602",
    label: "Voxtral Mini Transcribe 2",
    ratePerMin: 0.003,
    inputTokenRate: null as number | null,
    outputTokenRate: null as number | null,
    pricingLine: "$0.003 / min",
    maxAudioLength: 10800,
  },
  {
    value: "voxtral-mini-latest",
    label: "Voxtral Mini (latest)",
    ratePerMin: 0.003,
    inputTokenRate: null as number | null,
    outputTokenRate: null as number | null,
    pricingLine: "$0.003 / min",
    maxAudioLength: 10800,
  },
  {
    value: "voxtral-mini-2507",
    label: "Voxtral Mini Transcribe",
    ratePerMin: 0.003,
    inputTokenRate: null as number | null,
    outputTokenRate: null as number | null,
    pricingLine: "$0.003 / min",
    maxAudioLength: 900,
  },
  {
    value: "voxtral-small-2507",
    label: "Voxtral Small 2507",
    ratePerMin: 0.004,
    inputTokenRate: 0.0000001,
    outputTokenRate: 0.0000003,
    pricingLine: "$0.004 / min · in $0.1/M · out $0.3/M",
    maxAudioLength: 900,
  },
]

function formatDecimal(v: number | null | undefined): string {
  if (v == null) return ""
  if (v === 0) return "0"
  return v.toFixed(10).replace(/(\.\d*[1-9])0+$/, "$1").replace(/\.0+$/, "")
}

function ModelSelectItem({ model }: { model: (typeof MISTRAL_MODELS)[0] }) {
  return (
    <SelectPrimitive.Item
      value={model.value}
      className="relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
    >
      <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <Check className="h-4 w-4" />
        </SelectPrimitive.ItemIndicator>
      </span>
      <div className="flex flex-col min-w-0">
        <SelectPrimitive.ItemText>{model.label}</SelectPrimitive.ItemText>
        <span className="text-xs text-muted-foreground">{model.pricingLine}</span>
      </div>
    </SelectPrimitive.Item>
  )
}

export interface MistralSettingsFormProps {
  formData: Partial<SettingsPatch>
  onChange: (updates: Partial<SettingsPatch>) => void
}

export function MistralSettingsForm({
  formData,
  onChange,
}: MistralSettingsFormProps) {
  const handleModelChange = (value: string) => {
    const model = MISTRAL_MODELS.find((m) => m.value === value)
    if (!model) return

    // Clamp max_audio_length to model's cap
    const currentMaxAudioLength = formData.max_audio_length ?? 900
    const cappedMax = Math.min(currentMaxAudioLength, model.maxAudioLength)

    onChange({
      mistral_model: value,
      mistral_rate_usd_per_minute: model.ratePerMin,
      mistral_input_token_rate_usd: model.inputTokenRate,
      mistral_output_token_rate_usd: model.outputTokenRate,
      max_audio_length: cappedMax,
    })
  }

  const handleNumberChange = (field: keyof SettingsPatch) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    const num = value === "" ? 0 : parseFloat(value)
    onChange({ [field]: isNaN(num) ? 0 : num })
  }

  const selectedModel = MISTRAL_MODELS.find((m) => m.value === formData.mistral_model)
  const maxAudioLengthCap = selectedModel?.maxAudioLength ?? 10800

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="mistral-model">Model</Label>
        <Select
          value={formData.mistral_model || ""}
          onValueChange={handleModelChange}
        >
          <SelectTrigger className="w-full">
            <SelectValue placeholder="Select model" />
          </SelectTrigger>
          <SelectContent>
            {MISTRAL_MODELS.map((m) => (
              <ModelSelectItem key={m.value} model={m} />
            ))}
          </SelectContent>
        </Select>
      </div>

      <div className="space-y-2">
        <Label htmlFor="max-audio-length">
          Maximum Audio Length (seconds)
        </Label>
        <Input
          id="max-audio-length"
          type="number"
          min="60"
          max={maxAudioLengthCap}
          placeholder="900"
          value={formData.max_audio_length ?? ""}
          onChange={handleNumberChange("max_audio_length")}
        />
        <p className="text-sm text-muted-foreground">
          Audio files longer than this will be split. Minimum 60s, maximum{" "}
          {maxAudioLengthCap}s for the selected model.
        </p>
      </div>

      <div className="space-y-2">
        <div className="flex items-center gap-2">
          <Label htmlFor="audio-rate">Audio Rate (USD per minute)</Label>
          <Badge variant="outline" className="text-xs">
            Primary Billing
          </Badge>
        </div>
        <Input
          id="audio-rate"
          type="number"
          min="0"
          step="0.0001"
          placeholder="0.00"
          value={formData.mistral_rate_usd_per_minute ?? ""}
          onChange={handleNumberChange("mistral_rate_usd_per_minute")}
        />
        <p className="text-sm text-muted-foreground">
          Billed based on audio duration. Set to 0 to disable duration-based
          billing.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="input-token-rate">
              Input Token Rate (USD per token)
            </Label>
            <Badge variant="outline" className="text-xs">
              Optional
            </Badge>
          </div>
          <Input
            id="input-token-rate"
            type="text"
            inputMode="decimal"
            placeholder="0.00"
            value={formatDecimal(formData.mistral_input_token_rate_usd)}
            onChange={(e) => {
              const raw = e.target.value
              const num = raw === "" ? null : parseFloat(raw)
              onChange({
                mistral_input_token_rate_usd:
                  num !== null && !isNaN(num) ? num : null,
              })
            }}
          />
        </div>
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Label htmlFor="output-token-rate">
              Output Token Rate (USD per token)
            </Label>
            <Badge variant="outline" className="text-xs">
              Optional
            </Badge>
          </div>
          <Input
            id="output-token-rate"
            type="text"
            inputMode="decimal"
            placeholder="0.00"
            value={formatDecimal(formData.mistral_output_token_rate_usd)}
            onChange={(e) => {
              const raw = e.target.value
              const num = raw === "" ? null : parseFloat(raw)
              onChange({
                mistral_output_token_rate_usd:
                  num !== null && !isNaN(num) ? num : null,
              })
            }}
          />
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        Token-based billing is optional and used in addition to duration-based
        billing when configured. Leave blank to use only duration-based billing.
      </p>
    </div>
  )
}
