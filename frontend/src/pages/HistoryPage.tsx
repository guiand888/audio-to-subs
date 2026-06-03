// History page: table of completed jobs with aggregate statistics.
// Fetches from GET /api/history with pagination and filters.

import { useState, useEffect, useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, Filter } from "lucide-react"

import { api } from "@/lib/api"
import type { HistoryResponse, HistoryFilters, JobStatus, JobSource } from "@/lib/types"

// Import from shadcn/ui
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Badge } from "@/components/ui/badge"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { JobStatusIcon } from "@/components/JobStatusIcon"

const STATUS_OPTIONS: { value: JobStatus; label: string }[] = [
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
]

const SOURCE_OPTIONS: { value: JobSource; label: string }[] = [
  { value: "bazarr_movie", label: "Bazarr Movie" },
  { value: "bazarr_episode", label: "Bazarr Episode" },
  { value: "manual", label: "Manual" },
]

// Format cost as USD
function formatCost(cost: number | null | undefined): string {
  if (cost === null || cost === undefined) return "—"
  if (cost === 0) return "$0.00"
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(2)}`
  return `$${cost.toFixed(2)}`
}

// Format duration as human-readable string
function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—"
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.floor(seconds / 60)
  const secs = Math.round(seconds % 60)
  if (minutes < 60) return `${minutes}m ${secs}s`
  const hours = Math.floor(minutes / 60)
  const mins = minutes % 60
  return `${hours}h ${mins}m`
}

// Truncate a path for display
function truncatePath(path: string, maxLength: number = 50): string {
  if (path.length <= maxLength) return path
  const parts = path.split("/")
  const filename = parts[parts.length - 1]
  const dir = parts.slice(0, -1).join("/")
  if (filename.length > maxLength - 5) {
    return filename.slice(0, maxLength - 5) + "..."
  }
  if (dir.length > maxLength - filename.length - 5) {
    return ".../" + filename
  }
  return path
}

// Get status badge variant
function getStatusVariant(status: JobStatus): "default" | "secondary" | "destructive" {
  switch (status) {
    case "done":
      return "default"
    case "failed":
      return "destructive"
    case "cancelled":
      return "secondary"
    default:
      return "default"
  }
}

// Filter form component
interface HistoryFiltersProps {
  filters: HistoryFilters
  onChange: (filters: HistoryFilters) => void
}

function HistoryFiltersForm({ filters, onChange }: HistoryFiltersProps) {
  const [status, setStatus] = useState<JobStatus[]>(filters.status_filter || [])
  const [source, setSource] = useState<JobSource | undefined>(filters.source_filter)
  const [language, setLanguage] = useState<string | undefined>(filters.language_filter)

  const handleApply = () => {
    onChange({
      ...filters,
      status_filter: status.length > 0 ? status : undefined,
      source_filter: source,
      language_filter: language || undefined,
      offset: 0, // Reset to first page on filter change
    })
  }

  const handleReset = () => {
    setStatus([])
    setSource(undefined)
    setLanguage(undefined)
    onChange({ offset: 0 })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-medium">Filters</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="status-filter">Status</Label>
          <Select
            value={status.join(",")}
            onValueChange={(v) => setStatus(v.split(",") as JobStatus[])}
            multiple
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select statuses" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="source-filter">Source</Label>
          <Select
            value={source}
            onValueChange={(v) => setSource(v as JobSource)}
          >
            <SelectTrigger className="w-full">
              <SelectValue placeholder="Select source" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">All sources</SelectItem>
              {SOURCE_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <Label htmlFor="language-filter">Language</Label>
          <Input
            id="language-filter"
            type="text"
            placeholder="e.g. en, fr"
            value={language || ""}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-full"
          />
        </div>

        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handleReset}>
            Reset
          </Button>
          <Button size="sm" onClick={handleApply}>
            <Filter className="h-4 w-4 mr-2" />
            Apply
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// Stats display component
interface HistoryStatsProps {
  stats: HistoryResponse["stats"]
}

function HistoryStatsDisplay({ stats }: HistoryStatsProps) {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Total Jobs</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{stats.total_jobs}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Total Cost</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{formatCost(stats.total_cost_usd)}</div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Total Duration</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">
            {formatDuration(stats.total_duration_seconds)}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
          <CardTitle className="text-sm font-medium">Avg Cost/Job</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-2xl font-bold">{formatCost(stats.average_cost_usd)}</div>
        </CardContent>
      </Card>
    </div>
  )
}

// Main HistoryPage component
export function HistoryPage() {
  const [filters, setFilters] = useState<HistoryFilters>({ offset: 0, limit: 20 })
  const [page, setPage] = useState(0)

  // Build query string from filters
  const params = useMemo(() => {
    const p = new URLSearchParams()
    if (filters.status_filter?.length) {
      filters.status_filter.forEach((s) => p.append("status_filter", s))
    }
    if (filters.source_filter) p.set("source_filter", filters.source_filter)
    if (filters.language_filter) p.set("language_filter", filters.language_filter)
    if (filters.since) p.set("since", filters.since)
    if (filters.until) p.set("until", filters.until)
    p.set("limit", String(filters.limit || 20))
    p.set("offset", String(filters.offset || 0))
    return p.toString()
  }, [filters])

  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["history", filters],
    queryFn: () => api.get<HistoryResponse>(`/api/history?${params}`),
    staleTime: 30_000,
  })

  // Sync page state with filters
  useEffect(() => {
    const newPage = Math.floor((filters.offset || 0) / (filters.limit || 20))
    if (newPage !== page) setPage(newPage)
  }, [filters.offset, filters.limit, page])

  const handlePageChange = (newPage: number) => {
    setFilters({ ...filters, offset: newPage * (filters.limit || 20) })
  }

  const handleFiltersChange = (newFilters: HistoryFilters) => {
    setFilters(newFilters)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <p>Loading history...</p>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full">
        <p className="text-destructive">Failed to load history</p>
      </div>
    )
  }

  const response = data
  const jobs = response?.jobs || []
  const stats = response?.stats

  return (
    <div className="flex flex-col h-full p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">History</h1>
          <p className="text-sm text-muted-foreground">
            Completed transcription jobs
          </p>
        </div>
      </div>

      {/* Stats */}
      {stats && <HistoryStatsDisplay stats={stats} />}

      <div className="flex gap-4">
        {/* Filters sidebar */}
        <div className="w-full md:w-[250px] flex-none">
          <HistoryFiltersForm filters={filters} onChange={handleFiltersChange} />
        </div>

        {/* Jobs table */}
        <div className="flex-1 overflow-auto">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">Jobs</CardTitle>
              <CardDescription>
                {response?.total || 0} total completed jobs
              </CardDescription>
            </CardHeader>
            <CardContent>
              {jobs.length === 0 ? (
                <p className="text-muted-foreground text-center py-8">
                  No jobs found matching your filters
                </p>
              ) : (
                <Table>
                  <TableHeader className="bg-muted/50">
                    <TableRow>
                      <TableHead className="p-3">Status</TableHead>
                      <TableHead className="p-3">Source</TableHead>
                      <TableHead className="p-3">Media Path</TableHead>
                      <TableHead className="p-3">Language</TableHead>
                      <TableHead className="p-3">Duration</TableHead>
                      <TableHead className="p-3">Cost</TableHead>
                      <TableHead className="p-3">Created</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {jobs.map((job) => (
                      <TableRow key={job.id} className="border-t hover:bg-muted/50">
                        <TableCell className="p-3">
                          <div className="flex items-center gap-2">
                            <JobStatusIcon status={job.status} />
                            <span className="capitalize">{job.status}</span>
                          </div>
                        </TableCell>
                        <TableCell className="p-3">
                          <Badge variant="outline">
                            {job.source.replace("bazarr_", "")}
                          </Badge>
                          {job.source_ref && (
                            <span className="text-muted-foreground ml-2">
                              #{job.source_ref}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="p-3 max-w-[300px]">
                          <span className="truncate block" title={job.media_path}>
                            {truncatePath(job.media_path, 60)}
                          </span>
                        </TableCell>
                        <TableCell className="p-3">{job.language_code || "—"}</TableCell>
                        <TableCell className="p-3">{formatDuration(job.audio_duration_seconds)}</TableCell>
                        <TableCell className="p-3">{formatCost(job.estimated_cost_usd)}</TableCell>
                        <TableCell className="p-3 whitespace-nowrap">
                          {new Date(job.created_at).toLocaleString()}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}

              {/* Pagination */}
              {response && response.total > (filters.limit || 20) && (
                <div className="flex items-center justify-between pt-4">
                  <p className="text-sm text-muted-foreground">
                    Showing {(filters.offset || 0) + 1}-{Math.min(
                      (filters.offset || 0) + (filters.limit || 20),
                      response.total
                    )} of {response.total}
                  </p>
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={filters.offset === 0}
                      onClick={() => handlePageChange(page - 1)}
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    <span className="text-sm">
                      Page {page + 1} of {Math.ceil(response.total / (filters.limit || 20))}
                    </span>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={
                        filters.offset !== undefined &&
                        filters.offset + (filters.limit || 20) >= response.total
                      }
                      onClick={() => handlePageChange(page + 1)}
                    >
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
