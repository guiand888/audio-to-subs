// Settings page: Mistral pricing, Bazarr config, path mappings, defaults.
// Fetches from GET /api/settings and saves with PATCH /api/settings.

import { useState, useEffect, useMemo } from "react"
import { useBlocker } from "@tanstack/react-router"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, Plus, Trash2, Loader2 } from "lucide-react"
import { toast } from "sonner"

import { api } from "@/lib/api"
import type { SettingsOut, SettingsPatch } from "@/lib/types"

// Import from shadcn/ui
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import * as SelectPrimitive from "@radix-ui/react-select"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ApiError } from "@/lib/api"

function countChanges(formData: Partial<SettingsPatch>, settings: SettingsOut): number {
  let n = 0
  const diff = (a: unknown, b: unknown) => { if (a !== b) n++ }
  diff(formData.mistral_model, settings.mistral_model)
  diff(formData.mistral_rate_usd_per_minute, settings.mistral_rate_usd_per_minute)
  diff(formData.mistral_input_token_rate_usd, settings.mistral_input_token_rate_usd)
  diff(formData.mistral_output_token_rate_usd, settings.mistral_output_token_rate_usd)
  diff(formData.bazarr_poll_interval, settings.bazarr_poll_interval)
  diff(formData.bazarr_track_no_subs, settings.bazarr_track_no_subs)
  diff(formData.bazarr_url ?? "", settings.bazarr_url || "")
  diff(formData.bazarr_api_key ?? "", settings.bazarr_api_key || "")
  diff(formData.bazarr_timeout, settings.bazarr_timeout)
  diff(formData.default_language, settings.default_language)
  diff(formData.default_output_format, settings.default_output_format)
  diff(formData.movies_root_path ?? "", settings.movies_root_path || "")
  diff(formData.tv_root_path ?? "", settings.tv_root_path || "")
  diff(formData.subtitles_same_directory ?? true, settings.subtitles_same_directory ?? true)
  diff(JSON.stringify(formData.path_mappings ?? []), JSON.stringify(settings.path_mappings ?? []))
  return n
}

const MISTRAL_MODELS = [
  {
    value: "voxtral-mini-latest",
    label: "Voxtral Mini (latest)",
    ratePerMin: 0.003,
    inputTokenRate: null as number | null,
    outputTokenRate: null as number | null,
    pricingLine: "$0.003 / min",
  },
  {
    value: "voxtral-mini-2602",
    label: "Voxtral Mini 2602",
    ratePerMin: 0.003,
    inputTokenRate: null as number | null,
    outputTokenRate: null as number | null,
    pricingLine: "$0.003 / min",
  },
  {
    value: "voxtral-small-2507",
    label: "Voxtral Small 2507",
    ratePerMin: 0.004,
    inputTokenRate: 0.0000001,
    outputTokenRate: 0.0000003,
    pricingLine: "$0.004 / min · in $0.1/M · out $0.3/M",
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

// Output format options
const FORMAT_OPTIONS: { value: string; label: string }[] = [
  { value: "srt", label: "SRT" },
  { value: "vtt", label: "VTT" },
  { value: "webvtt", label: "WebVTT" },
  { value: "sbv", label: "SBV" },
]

// Common language options
const LANGUAGE_OPTIONS = [
  { value: "en", label: "English" },
  { value: "fr", label: "French" },
  { value: "es", label: "Spanish" },
  { value: "de", label: "German" },
  { value: "it", label: "Italian" },
  { value: "pt", label: "Portuguese" },
  { value: "ru", label: "Russian" },
  { value: "zh", label: "Chinese" },
  { value: "ja", label: "Japanese" },
  { value: "ar", label: "Arabic" },
]

// Main SettingsPage component
export function SettingsPage() {
  const queryClient = useQueryClient()
  const {
    data: settings,
    isLoading,
    isError,
    refetch,
  } = useQuery({
    queryKey: ["settings"],
    queryFn: () => api.get<SettingsOut>("/api/settings"),
    staleTime: 60_000, // Don't auto-refetch too often
  })

  const mutation = useMutation({
    mutationFn: (patch: SettingsPatch) => api.patch<SettingsOut>("/api/settings", patch),
    onSuccess: () => {
      toast.success("Settings saved")
      void queryClient.invalidateQueries({ queryKey: ["settings"] })
      // Also invalidate other queries that might depend on settings
      void queryClient.invalidateQueries({ queryKey: ["wanted"] })
      void queryClient.invalidateQueries({ queryKey: ["jobs"] })
    },
    onError: (err) => {
      if (err instanceof ApiError) {
        toast.error(`Save failed: ${err.detail}`)
      } else {
        toast.error("Save failed")
      }
    },
  })

  // Form state
  const [formData, setFormData] = useState<Partial<SettingsPatch>>({})

  const changeCount = useMemo(
    () => (settings ? countChanges(formData, settings) : 0),
    [formData, settings],
  )

  const blocker = useBlocker({
    shouldBlockFn: () => changeCount > 0,
    withResolver: true,
    enableBeforeUnload: true,
    disabled: changeCount === 0,
  })

  // Sync form data with fetched settings
  useEffect(() => {
    if (settings) {
      setFormData({
        mistral_model: settings.mistral_model,
        mistral_rate_usd_per_minute: settings.mistral_rate_usd_per_minute,
        mistral_input_token_rate_usd: settings.mistral_input_token_rate_usd,
        mistral_output_token_rate_usd: settings.mistral_output_token_rate_usd,
        bazarr_poll_interval: settings.bazarr_poll_interval,
        bazarr_track_no_subs: settings.bazarr_track_no_subs,
        bazarr_url: settings.bazarr_url || "",
        bazarr_api_key: settings.bazarr_api_key || "",
        bazarr_timeout: settings.bazarr_timeout,
        path_mappings: settings.path_mappings as any,
        default_language: settings.default_language,
        default_output_format: settings.default_output_format,
        movies_root_path: settings.movies_root_path || "",
        tv_root_path: settings.tv_root_path || "",
        subtitles_same_directory: settings.subtitles_same_directory ?? true,
      })
    }
  }, [settings])

  const handleSave = () => {
    // Clean up the form data - remove undefined values
    const cleanData: SettingsPatch = {}
    for (const [key, value] of Object.entries(formData)) {
      if (value !== undefined) {
        // @ts-expect-error - dynamic key access
        cleanData[key] = value
      }
    }
    // bazarr_url/bazarr_api_key use an empty string as an explicit "disable
    // Bazarr" signal server-side (it's not overridden by env-var fallback).
    // Only send them when the user actually changed them, so saving an
    // unrelated field doesn't silently disable env-configured Bazarr.
    if (settings) {
      if ((formData.bazarr_url ?? "") === (settings.bazarr_url || "")) {
        delete cleanData.bazarr_url
      }
      if ((formData.bazarr_api_key ?? "") === (settings.bazarr_api_key || "")) {
        delete cleanData.bazarr_api_key
      }
    }
    mutation.mutate(cleanData)
  }

  const handleNumberChange = (field: keyof SettingsPatch) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value
    const num = value === "" ? 0 : parseFloat(value)
    setFormData({ ...formData, [field]: isNaN(num) ? 0 : num })
  }

  const handleBooleanChange = (field: keyof SettingsPatch) => (checked: boolean) => {
    setFormData({ ...formData, [field]: checked })
  }

  const handleSelectChange = (field: keyof SettingsPatch) => (value: string) => {
    setFormData({ ...formData, [field]: value })
  }

  const handleModelChange = (value: string) => {
    const model = MISTRAL_MODELS.find((m) => m.value === value)
    if (!model) return
    setFormData((prev) => ({
      ...prev,
      mistral_model: value,
      mistral_rate_usd_per_minute: model.ratePerMin,
      mistral_input_token_rate_usd: model.inputTokenRate,
      mistral_output_token_rate_usd: model.outputTokenRate,
    }))
  }

  // Path mappings management
  const addPathMapping = () => {
    const currentMappings = (formData.path_mappings as Array<{ from: string; to: string }>) || []
    setFormData({
      ...formData,
      path_mappings: [...currentMappings, { from: "", to: "" }],
    })
  }

  const removePathMapping = (index: number) => {
    const currentMappings = (formData.path_mappings as Array<{ from: string; to: string }>) || []
    const newMappings = currentMappings.filter((_, i) => i !== index)
    setFormData({ ...formData, path_mappings: newMappings })
  }

  const updatePathMapping = (index: number, field: "from" | "to") => (e: React.ChangeEvent<HTMLInputElement>) => {
    const currentMappings = (formData.path_mappings as Array<{ from: string; to: string }>) || []
    const newMappings = [...currentMappings]
    newMappings[index] = { ...newMappings[index], [field]: e.target.value }
    setFormData({ ...formData, path_mappings: newMappings })
  }

  if (isLoading && !settings) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin" />
        <span className="ml-2">Loading settings...</span>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-destructive">Failed to load settings</p>
        <Button onClick={() => void refetch()}>Retry</Button>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full p-4 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Configure transcription and integration settings
          </p>
        </div>
        <div className="flex items-center gap-3">
          {changeCount > 0 && (
            <span className="text-xs text-muted-foreground">
              {changeCount} {changeCount === 1 ? "change" : "changes"}
            </span>
          )}
          <Button onClick={handleSave} disabled={mutation.isPending}>
            {mutation.isPending ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Check className="h-4 w-4 mr-2" />
                Save Settings
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Unsaved-changes navigation guard */}
      <Dialog open={blocker.status === "blocked"} onOpenChange={() => blocker.reset?.()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Unsaved changes</DialogTitle>
            <DialogDescription>
              You have {changeCount} unsaved {changeCount === 1 ? "change" : "changes"}.
              Leave without saving?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => blocker.reset?.()}>
              Stay
            </Button>
            <Button variant="destructive" onClick={() => blocker.proceed?.()}>
              Leave
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <div className="space-y-6 max-w-4xl">
        {/* Mistral Configuration */}
        <Card>
          <CardHeader>
            <CardTitle>Mistral AI Configuration</CardTitle>
            <CardDescription>
              Configure which model to use and billing rates
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
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
              <div className="flex items-center gap-2">
                <Label htmlFor="audio-rate">Audio Rate (USD per minute)</Label>
                <Badge variant="outline" className="text-xs">Primary Billing</Badge>
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
                Billed based on audio duration. Set to 0 to disable duration-based billing.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Label htmlFor="input-token-rate">Input Token Rate (USD per token)</Label>
                  <Badge variant="outline" className="text-xs">Optional</Badge>
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
                    setFormData((prev) => ({
                      ...prev,
                      mistral_input_token_rate_usd: num !== null && !isNaN(num) ? num : null,
                    }))
                  }}
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <Label htmlFor="output-token-rate">Output Token Rate (USD per token)</Label>
                  <Badge variant="outline" className="text-xs">Optional</Badge>
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
                    setFormData((prev) => ({
                      ...prev,
                      mistral_output_token_rate_usd: num !== null && !isNaN(num) ? num : null,
                    }))
                  }}
                />
              </div>
            </div>
            <p className="text-sm text-muted-foreground">
              Token-based billing is optional and used in addition to duration-based billing when configured.
              Leave blank to use only duration-based billing.
            </p>
          </CardContent>
        </Card>

        {/* Bazarr Configuration */}
        <Card>
          <CardHeader>
            <CardTitle>Bazarr Configuration</CardTitle>
            <CardDescription>
              Configure Bazarr integration for automatic subtitle detection
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="bazarr-url">Bazarr API URL</Label>
              <Input
                id="bazarr-url"
                type="url"
                placeholder="http://bazarr:6767"
                value={formData.bazarr_url ?? ""}
                onChange={(e) => setFormData({ ...formData, bazarr_url: e.target.value })}
              />
              <p className="text-sm text-muted-foreground">
                Base URL for Bazarr API (e.g., http://bazarr:6767)
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="bazarr-api-key">API Key</Label>
              <Input
                id="bazarr-api-key"
                type="password"
                placeholder="Enter your Bazarr API key"
                value={formData.bazarr_api_key ?? ""}
                onChange={(e) => setFormData({ ...formData, bazarr_api_key: e.target.value })}
              />
              <p className="text-sm text-muted-foreground">
                Bazarr API key for authentication
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="bazarr-timeout">API Timeout (seconds)</Label>
              <Input
                id="bazarr-timeout"
                type="number"
                min="1"
                max="300"
                step="0.1"
                placeholder="30"
                value={formData.bazarr_timeout ?? ""}
                onChange={handleNumberChange("bazarr_timeout")}
              />
              <p className="text-sm text-muted-foreground">
                Timeout for Bazarr API requests (1-300 seconds)
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="poll-interval">Poll Interval (seconds)</Label>
              <Input
                id="poll-interval"
                type="number"
                min="0"
                placeholder="3600"
                value={formData.bazarr_poll_interval ?? ""}
                onChange={handleNumberChange("bazarr_poll_interval")}
              />
              <p className="text-sm text-muted-foreground">
                How often to poll Bazarr for new items missing subtitles.
              </p>
            </div>

            <div className="flex items-center justify-between">
              <div>
                <Label htmlFor="track-no-subs">Track Items with No Subtitles</Label>
                <p className="text-sm text-muted-foreground">
                  Include items that have no subtitles in any language.
                </p>
              </div>
              <Switch
                id="track-no-subs"
                checked={formData.bazarr_track_no_subs ?? false}
                onCheckedChange={handleBooleanChange("bazarr_track_no_subs")}
              />
            </div>
          </CardContent>
        </Card>

        {/* Media Paths Configuration */}
        <Card>
          <CardHeader>
            <CardTitle>Media Paths</CardTitle>
            <CardDescription>
              Configure root directories for movies and TV shows (aligned with Radarr/Sonarr/Bazarr)
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="movies-root-path">Movies Root Path</Label>
                <Input
                  id="movies-root-path"
                  type="text"
                  placeholder="/movies"
                  value={formData.movies_root_path ?? ""}
                  onChange={(e) => setFormData({ ...formData, movies_root_path: e.target.value })}
                />
                <p className="text-sm text-muted-foreground">
                  Root directory for movie files (e.g., /movies)
                </p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="tv-root-path">TV Root Path</Label>
                <Input
                  id="tv-root-path"
                  type="text"
                  placeholder="/tv"
                  value={formData.tv_root_path ?? ""}
                  onChange={(e) => setFormData({ ...formData, tv_root_path: e.target.value })}
                />
                <p className="text-sm text-muted-foreground">
                  Root directory for TV series files (e.g., /tv)
                </p>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="subtitles-same-directory">Save Subtitles Alongside Video Files</Label>
                  <p className="text-sm text-muted-foreground">
                    When enabled, subtitles will be saved in the same directory as the source video file
                  </p>
                </div>
                <Switch
                  id="subtitles-same-directory"
                  checked={formData.subtitles_same_directory ?? true}
                  onCheckedChange={(checked) => setFormData({ ...formData, subtitles_same_directory: checked })}
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Default Values */}
        <Card>
          <CardHeader>
            <CardTitle>Default Values</CardTitle>
            <CardDescription>
              Default values for new jobs
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="default-language">Default Language</Label>
                <Select
                  value={formData.default_language || ""}
                  onValueChange={handleSelectChange("default_language")}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select language" />
                  </SelectTrigger>
                  <SelectContent>
                    {LANGUAGE_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="default-format">Default Output Format</Label>
                <Select
                  value={formData.default_output_format || ""}
                  onValueChange={handleSelectChange("default_output_format")}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="Select format" />
                  </SelectTrigger>
                  <SelectContent>
                    {FORMAT_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Path Mappings */}
        <Card>
          <CardHeader>
            <CardTitle>Path Mappings</CardTitle>
            <CardDescription>
              Map paths from Bazarr to the worker container filesystem
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <Button size="sm" onClick={addPathMapping}>
                <Plus className="h-4 w-4 mr-2" />
                Add Mapping
              </Button>

              {((formData.path_mappings as Array<{ from: string; to: string }>) || []).length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>From</TableHead>
                      <TableHead>To</TableHead>
                      <TableHead className="text-right">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {((formData.path_mappings as Array<{ from: string; to: string }>) || []).map(
                      (mapping, index) => (
                        <TableRow key={index}>
                          <TableCell>
                            <Input
                              type="text"
                              placeholder="Bazarr path"
                              value={mapping.from}
                              onChange={updatePathMapping(index, "from")}
                            />
                          </TableCell>
                          <TableCell>
                            <Input
                              type="text"
                              placeholder="Worker path"
                              value={mapping.to}
                              onChange={updatePathMapping(index, "to")}
                            />
                          </TableCell>
                          <TableCell className="text-right">
                            <Button
                              size="sm"
                              variant="destructive"
                              onClick={() => removePathMapping(index)}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </TableCell>
                        </TableRow>
                      )
                    )}
                  </TableBody>
                </Table>
              ) : (
                <p className="text-muted-foreground text-center py-4">
                  No path mappings configured. Add mappings to translate Bazarr paths to paths accessible by the worker.
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
