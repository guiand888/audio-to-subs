// Wanted page: search, tabs (All/Movies/Series), only-no-subs toggle,
// missing-lang filter, table, live active-job indicator, Transcribe dialog.

import { useState, useEffect, useMemo } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { Loader2, Search } from "lucide-react"
import { toast } from "sonner"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
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
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useWanted } from "@/hooks/useWanted"
import { useCreateJob } from "@/hooks/useJobs"
import { useJobsStore } from "@/lib/jobsStore"
import { ApiError } from "@/lib/api"
import type { MissingSubtitle, OutputFormat, WantedItem } from "@/lib/types"

type ItemType = "all" | "movie" | "episode"

// Derive a clean language label from a MissingSubtitle
function langLabel(ms: MissingSubtitle): string {
  let label = ms.name ?? ms.code2
  if (ms.hi) label += " HI"
  if (ms.forced) label += " Forced"
  return label
}

// ── Transcribe dialog ─────────────────────────────────────────────────────────

interface TranscribeDialogProps {
  item: WantedItem | null
  onClose: () => void
}

const FORMAT_OPTIONS: OutputFormat[] = ["srt", "vtt", "webvtt", "sbv"]

function TranscribeDialog({ item, onClose }: TranscribeDialogProps) {
  const createJob = useCreateJob()
  const [language, setLanguage] = useState<string>("")
  const [format, setFormat] = useState<OutputFormat>("srt")

  // Pre-select first missing language when item changes
  useEffect(() => {
    if (item?.missing_subtitles.length) {
      setLanguage(item.missing_subtitles[0].code2)
    } else {
      setLanguage("")
    }
    setFormat("srt")
  }, [item])

  if (!item) return null

  const handleSubmit = () => {
    createJob.mutate(
      {
        source: item.kind === "movie" ? "bazarr_movie" : "bazarr_episode",
        source_ref: String(item.ext_id),
        media_path: item.media_path,
        language_code: language || null,
        output_format: format,
      },
      {
        onSuccess: () => {
          toast.success("Job queued")
          onClose()
        },
        onError: (err) => {
          if (err instanceof ApiError && err.status === 409) {
            toast.error("A job for this item is already active")
          } else {
            toast.error("Failed to queue job")
          }
          onClose()
        },
      },
    )
  }

  return (
    <Dialog open={!!item} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>Transcribe</DialogTitle>
        </DialogHeader>
        <div className="space-y-1 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{item.title}</span>
        </div>

        <div className="space-y-4 pt-2">
          {/* Language */}
          <div className="space-y-1.5">
            <Label>Language</Label>
            {item.missing_subtitles.length > 0 ? (
              <Select value={language} onValueChange={setLanguage}>
                <SelectTrigger>
                  <SelectValue placeholder="Select language" />
                </SelectTrigger>
                <SelectContent>
                  {item.missing_subtitles.map((ms) => (
                    <SelectItem key={ms.code2} value={ms.code2}>
                      {langLabel(ms)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Input
                placeholder="e.g. en"
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
              />
            )}
          </div>

          {/* Format */}
          <div className="space-y-1.5">
            <Label>Output format</Label>
            <Select
              value={format}
              onValueChange={(v) => setFormat(v as OutputFormat)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {FORMAT_OPTIONS.map((f) => (
                  <SelectItem key={f} value={f}>
                    {f.toUpperCase()}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={createJob.isPending}
          >
            {createJob.isPending ? "Queuing…" : "Queue job"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

// ── WantedPage ────────────────────────────────────────────────────────────────

export function WantedPage() {
  const queryClient = useQueryClient()
  const [itemType, setItemType] = useState<ItemType>("all")
  const [search, setSearch] = useState("")
  const [onlyNoSubs, setOnlyNoSubs] = useState(false)
  const [langFilter, setLangFilter] = useState<string>("")
  const [page, setPage] = useState(1)
  const [transcribeItem, setTranscribeItem] = useState<WantedItem | null>(null)

  // Invalidate wanted query when a job finishes
  const lastTerminalJobId = useJobsStore((s) => s.lastTerminalJobId)
  useEffect(() => {
    if (lastTerminalJobId) {
      void queryClient.invalidateQueries({ queryKey: ["wanted"] })
    }
  }, [lastTerminalJobId, queryClient])

  const { data, isLoading } = useWanted({
    item_type: itemType,
    page,
    page_size: 50,
  })

  // Client-side search + filter (simple approach for now)
  const items = useMemo(() => {
    if (!data?.items) return []
    let list = data.items
    if (search) {
      const q = search.toLowerCase()
      list = list.filter((i) => i.title.toLowerCase().includes(q))
    }
    if (onlyNoSubs) {
      list = list.filter((i) => !i.has_any_subs)
    }
    if (langFilter) {
      list = list.filter((i) =>
        i.missing_subtitles.some((ms) => ms.code2 === langFilter),
      )
    }
    return list
  }, [data?.items, search, onlyNoSubs, langFilter])

  // Derive language options from all visible items
  const langOptions = useMemo(() => {
    if (!data?.items) return []
    const codes = new Set<string>()
    for (const item of data.items) {
      for (const ms of item.missing_subtitles) codes.add(ms.code2)
    }
    return [...codes].sort()
  }, [data?.items])

  const totalPages = data ? Math.ceil(data.total / 50) : 1

  return (
    <div className="flex flex-col h-full">
      {/* Toolbar */}
      <div className="flex flex-wrap gap-3 items-center border-b px-4 py-3 bg-muted/30">
        {/* Search */}
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search…"
            className="pl-8"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              setPage(1)
            }}
          />
        </div>

        {/* Tabs */}
        <Tabs
          value={itemType}
          onValueChange={(v) => {
            setItemType(v as ItemType)
            setPage(1)
          }}
        >
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="movie">Movies</TabsTrigger>
            <TabsTrigger value="episode">Series</TabsTrigger>
          </TabsList>
        </Tabs>

        {/* Only no-subs */}
        <div className="flex items-center gap-2">
          <Switch
            id="only-no-subs"
            checked={onlyNoSubs}
            onCheckedChange={(v) => {
              setOnlyNoSubs(v)
              setPage(1)
            }}
          />
          <Label htmlFor="only-no-subs" className="text-sm cursor-pointer">
            No subtitles only
          </Label>
        </div>

        {/* Language filter */}
        {langOptions.length > 0 && (
          <Select
            value={langFilter || "_all"}
            onValueChange={(v) => {
              setLangFilter(v === "_all" ? "" : v)
              setPage(1)
            }}
          >
            <SelectTrigger className="w-[120px]">
              <SelectValue placeholder="Language" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="_all">All langs</SelectItem>
              {langOptions.map((code) => (
                <SelectItem key={code} value={code}>
                  {code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {/* Table */}
      <div className="flex-1 overflow-auto">
        {isLoading ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : items.length === 0 ? (
          <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
            No items found.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="min-w-[200px]">Title</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Missing</TableHead>
                <TableHead className="text-right">Action</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((item) => (
                <WantedRow
                  key={item.id}
                  item={item}
                  onTranscribe={() => setTranscribeItem(item)}
                />
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t px-4 py-2 text-sm text-muted-foreground">
          <span>
            Page {page} of {totalPages} — {data?.total ?? 0} items
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      <TranscribeDialog
        item={transcribeItem}
        onClose={() => setTranscribeItem(null)}
      />
    </div>
  )
}

// ── WantedRow ─────────────────────────────────────────────────────────────────

interface WantedRowProps {
  item: WantedItem
  onTranscribe: () => void
}

function WantedRow({ item, onTranscribe }: WantedRowProps) {
  // Pull live active-job info from the SSE store (may be more up-to-date than the API)
  const liveJob = useJobsStore((s) =>
    item.active_job_id ? s.jobs[item.active_job_id] : null,
  )
  const hasActiveJob =
    liveJob != null || (item.active_job_id != null && item.active_job_status != null)

  return (
    <TableRow>
      <TableCell className="font-medium">
        <span className="flex items-center gap-1.5">
          {hasActiveJob && (
            <Loader2
              className="h-3.5 w-3.5 animate-spin text-muted-foreground flex-none"
              aria-label="Job active"
            />
          )}
          {item.title}
        </span>
      </TableCell>
      <TableCell className="text-muted-foreground capitalize">
        {item.kind}
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {item.missing_subtitles.map((ms) => (
            <Badge key={ms.code2} variant="outline" className="text-xs">
              {langLabel(ms)}
            </Badge>
          ))}
          {item.missing_subtitles.length === 0 && (
            <span className="text-xs text-muted-foreground">—</span>
          )}
        </div>
      </TableCell>
      <TableCell className="text-right">
        <Button
          size="sm"
          variant="outline"
          onClick={onTranscribe}
          disabled={hasActiveJob}
        >
          Transcribe
        </Button>
      </TableCell>
    </TableRow>
  )
}
