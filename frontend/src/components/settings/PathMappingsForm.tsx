import { Plus, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import type { SettingsPatch } from "@/lib/types"

export interface PathMappingsFormProps {
  formData: Partial<SettingsPatch>
  onChange: (updates: Partial<SettingsPatch>) => void
}

export function PathMappingsForm({
  formData,
  onChange,
}: PathMappingsFormProps) {
  const addPathMapping = () => {
    const currentMappings =
      (formData.path_mappings as Array<{ from: string; to: string }>) || []
    onChange({
      path_mappings: [...currentMappings, { from: "", to: "" }],
    })
  }

  const removePathMapping = (index: number) => {
    const currentMappings =
      (formData.path_mappings as Array<{ from: string; to: string }>) || []
    const newMappings = currentMappings.filter((_, i) => i !== index)
    onChange({ path_mappings: newMappings })
  }

  const updatePathMapping =
    (index: number, field: "from" | "to") =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const currentMappings =
        (formData.path_mappings as Array<{ from: string; to: string }>) || []
      const newMappings = [...currentMappings]
      newMappings[index] = { ...newMappings[index], [field]: e.target.value }
      onChange({ path_mappings: newMappings })
    }

  const mappings =
    (formData.path_mappings as Array<{ from: string; to: string }>) || []

  return (
    <div className="space-y-4">
      <Button size="sm" onClick={addPathMapping}>
        <Plus className="h-4 w-4 mr-2" />
        Add Mapping
      </Button>

      {mappings.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>From</TableHead>
              <TableHead>To</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {mappings.map((mapping, index) => (
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
            ))}
          </TableBody>
        </Table>
      ) : (
        <p className="text-sm text-muted-foreground text-center py-4">
          No path mappings configured. Add mappings to translate Bazarr paths to
          paths accessible by the worker.
        </p>
      )}
    </div>
  )
}
