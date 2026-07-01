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
  diff(formData.default_language, settings.default_language)
  diff(formData.default_output_format, settings.default_output_format)
  diff(formData.movies_root_path ?? "", settings.movies_root_path || "")
  diff(formData.tv_root_path ?? "", settings.tv_root_path || "")
  diff(formData.subtitles_same_directory ?? true, settings.subtitles_same_directory ?? true)
  diff(JSON.stringify(formData.path_mappings ?? []), JSON.stringify(settings.path_mappings ?? []))
  return n
}

// Common Mistral models
const MISTRAL_MODEL_OPTIONS = [
  { value: "mistral-medium-latest", label: "Mistral Medium Latest" },
  { value: "voxtral-mini-latest", label: "Voxtral Mini Latest" },
  { value: "mistral-small-latest", label: "Mistral Small Latest" },
  { value: "mistral-large-latest", label: "Mistral Large Latest" },
]

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
                onValueChange={handleSelectChange("mistral_model")}
              >
                <SelectTrigger className="w-full">
                  <SelectValue placeholder="Select model" />
                </SelectTrigger>
                <SelectContent>
                  {MISTRAL_MODEL_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label htmlFor="audio-rate">
                Audio Rate (USD per minute)
                <Badge variant="outline" className="ml-2 text-xs">
                  Primary billing
                </Badge>
              </Label>
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
                <Label htmlFor="input-token-rate">
                  Input Token Rate (USD per token)
                  <Badge variant="outline" className="ml-2 text-xs">
                    Optional
                  </Badge>
                </Label>
                <Input
                  id="input-token-rate"
                  type="number"
                  min="0"
                  step="0.000001"
                  placeholder="0.00"
                  value={formData.mistral_input_token_rate_usd ?? ""}
                  onChange={handleNumberChange("mistral_input_token_rate_usd")}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="output-token-rate">
                  Output Token Rate (USD per token)
                  <Badge variant="outline" className="ml-2 text-xs">
                    Optional
                  </Badge>
                </Label>
                <Input
                  id="output-token-rate"
                  type="number"
                  min="0"
                  step="0.000001"
                  placeholder="0.00"
                  value={formData.mistral_output_token_rate_usd ?? ""}
                  onChange={handleNumberChange("mistral_output_token_rate_usd")}
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
