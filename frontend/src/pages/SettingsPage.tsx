// Settings page: Mistral pricing, Bazarr config, path mappings, defaults.
// Fetches from GET /api/settings and saves with PATCH /api/settings.
// Composed from reusable sub-form components.

import { useBlocker } from "@tanstack/react-router"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Check, Loader2 } from "lucide-react"
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
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ApiError } from "@/lib/api"

// Import sub-form components
import { MistralSettingsForm } from "@/components/settings/MistralSettingsForm"
import { BazarrSettingsForm } from "@/components/settings/BazarrSettingsForm"
import { PathMappingsForm } from "@/components/settings/PathMappingsForm"
import { LocalizationSettingsForm } from "@/components/settings/LocalizationSettingsForm"

// Import the form state hook
import { useSettingsForm } from "@/hooks/useSettingsForm"

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

  // Use the form state hook (declared before the mutation so its onSuccess
  // closure can call resetFromSettings)
  const { formData, updateFormData, changeCount, resetFromSettings } = useSettingsForm(settings)

  const mutation = useMutation({
    mutationFn: (patch: SettingsPatch) => api.patch<SettingsOut>("/api/settings", patch),
    onSuccess: (response) => {
      toast.success("Settings saved")
      // The PATCH response is the authoritative sanitized settings. Write it
      // into the cache AND rebuild the form baseline explicitly: React
      // Query's structural sharing means a refetch/cache-write that's deeply
      // equal to what's already cached (e.g. bazarr_api_key masked -> masked,
      // when the key was the only saved change) keeps the same object
      // reference, so useSettingsForm's resync effect would never fire and
      // the "unsaved changes" indicator would stay stuck. We intentionally do
      // NOT invalidateQueries(["settings"]) afterwards - settings is a
      // low-concurrency resource and the response is authoritative, so a
      // background refetch would race with this update for no benefit.
      queryClient.setQueryData(["settings"], response)
      resetFromSettings(response)
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

  const blocker = useBlocker({
    shouldBlockFn: () => changeCount > 0,
    withResolver: true,
    enableBeforeUnload: true,
    disabled: changeCount === 0,
  })

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

  const handleSelectChange = (field: keyof SettingsPatch) => (value: string) => {
    updateFormData({ [field]: value })
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
          <CardContent>
            <MistralSettingsForm formData={formData} onChange={updateFormData} />
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
          <CardContent>
            <BazarrSettingsForm formData={formData} onChange={updateFormData} />
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
                  onChange={(e) => updateFormData({ movies_root_path: e.target.value })}
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
                  onChange={(e) => updateFormData({ tv_root_path: e.target.value })}
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
                  onCheckedChange={(checked) => updateFormData({ subtitles_same_directory: checked })}
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
            <PathMappingsForm formData={formData} onChange={updateFormData} />
          </CardContent>
        </Card>

        {/* Localization */}
        <Card>
          <CardHeader>
            <CardTitle>Localization</CardTitle>
            <CardDescription>
              Choose how times are displayed throughout the UI
            </CardDescription>
          </CardHeader>
          <CardContent>
            <LocalizationSettingsForm formData={formData} onChange={updateFormData} />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
