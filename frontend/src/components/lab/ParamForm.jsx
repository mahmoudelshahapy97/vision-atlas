import { Link as RouterLink } from "react-router-dom";
import Accordion from "@mui/material/Accordion";
import AccordionDetails from "@mui/material/AccordionDetails";
import AccordionSummary from "@mui/material/AccordionSummary";
import Autocomplete from "@mui/material/Autocomplete";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormHelperText from "@mui/material/FormHelperText";
import Link from "@mui/material/Link";
import MenuItem from "@mui/material/MenuItem";
import Slider from "@mui/material/Slider";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import EditIcon from "@mui/icons-material/Edit";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";

export const GEOMETRY = new Set(["line", "polygon", "polygons", "points", "box"]);

function geoSummary(p, v) {
  if (p.type === "line") return v?.length === 2 ? "Line set" : "Not drawn";
  if (p.type === "box") return v?.length === 2 ? "Box set" : "Not drawn";
  if (p.type === "polygon") return v?.length >= 3 ? `${v.length} points` : v?.length ? `${v.length} points (need 3+)` : "Not drawn";
  if (p.type === "polygons") return v?.length ? `${v.length} shape${v.length > 1 ? "s" : ""}` : "None drawn";
  if (p.type === "points") return v?.length ? `${v.length} point${v.length > 1 ? "s" : ""}` : "No points";
  return "";
}

const Label = ({ children, htmlFor }) => (
  <Typography component={htmlFor ? "label" : "span"} htmlFor={htmlFor} variant="body2" sx={{ fontWeight: 600, display: "block", mb: 0.5 }}>
    {children}
  </Typography>
);

const Help = ({ children }) => (children ? <FormHelperText sx={{ mx: 0 }}>{children}</FormHelperText> : null);

/** Short option lists are toggle chips; long ones (e.g. 80 COCO classes) a searchable picker. Empty means all. */
function MultiSelect({ p, value, onChange }) {
  const sel = value || [];
  const options = p.options || [];
  if (options.length <= 12) {
    const toggle = (o) => onChange(sel.includes(o) ? sel.filter((x) => x !== o) : [...sel, o]);
    return (
      <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
        {options.map((o) => (
          <Chip
            key={o}
            label={o}
            size="small"
            clickable
            color={sel.includes(o) ? "primary" : "default"}
            variant={sel.includes(o) ? "filled" : "outlined"}
            aria-pressed={sel.includes(o)}
            onClick={() => toggle(o)}
          />
        ))}
      </Stack>
    );
  }
  return (
    <Autocomplete
      multiple
      size="small"
      options={options}
      value={sel}
      onChange={(_, v) => onChange(v)}
      getOptionLabel={String}
      filterSelectedOptions
      renderInput={(params) => (
        <TextField {...params} id={`ms-${p.name}`} placeholder={sel.length ? "Add a class…" : "All classes · add to narrow"} />
      )}
    />
  );
}

function Field({ p, value, onChange, activeGeo, setActiveGeo, hasImage }) {
  const id = `p-${p.name}`;
  if (GEOMETRY.has(p.type)) {
    const active = activeGeo === p.name;
    const hasValue = value && (Array.isArray(value) ? value.length > 0 : true);
    return (
      <Box>
        <Label>{p.label}</Label>
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
          <Typography variant="caption" color="text.secondary">{geoSummary(p, value)}</Typography>
          <Stack direction="row" spacing={1}>
            <Button size="small" variant={active ? "contained" : "outlined"} disabled={!hasImage} startIcon={<EditIcon />}
              onClick={() => setActiveGeo(active ? null : p.name)}>
              {active ? "Done drawing" : "Draw on image"}
            </Button>
            {hasValue && (
              <Button size="small" color="inherit" onClick={() => onChange(Array.isArray(p.default) ? [] : null)}>Clear</Button>
            )}
          </Stack>
        </Stack>
        <Help>{p.help}</Help>
        {!hasImage && <Help>Add an input first, then draw on it.</Help>}
      </Box>
    );
  }
  if (p.type === "bool") {
    return (
      <Box>
        <FormControlLabel
          control={<Checkbox id={id} checked={!!value} onChange={(e) => onChange(e.target.checked)} />}
          label={<Typography variant="body2" sx={{ fontWeight: 600 }}>{p.label}</Typography>}
        />
        <Help>{p.help}</Help>
      </Box>
    );
  }
  if (p.type === "number" || p.type === "int") {
    const step = p.step ?? (p.type === "int" ? 1 : 0.01);
    const useSlider = p.min !== undefined && p.max !== undefined && Math.abs(p.max - p.min) <= 1e4;
    return (
      <Box>
        <Label htmlFor={id}>{p.label}</Label>
        <Stack direction="row" spacing={2} alignItems="center">
          {useSlider && (
            <Slider size="small" min={p.min} max={p.max} step={step} value={value ?? p.min} aria-label={p.label}
              onChange={(_, v) => onChange(v)} sx={{ flexGrow: 1 }} />
          )}
          <TextField
            id={id}
            type="number"
            size="small"
            value={value ?? ""}
            onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
            inputProps={{ min: p.min, max: p.max, step }}
            sx={{ width: useSlider ? 104 : "100%", flexShrink: 0 }}
          />
        </Stack>
        <Help>{p.help}</Help>
      </Box>
    );
  }
  if (p.type === "select") {
    return (
      <TextField
        id={id}
        select
        size="small"
        fullWidth
        label={p.label}
        value={String(value ?? "")}
        onChange={(e) => {
          const o = p.options.find((x) => String(x) === e.target.value);
          onChange(o ?? e.target.value);
        }}
        helperText={p.help}
      >
        {p.options.map((o) => <MenuItem key={String(o)} value={String(o)}>{String(o)}</MenuItem>)}
      </TextField>
    );
  }
  if (p.type === "multiselect") {
    return (
      <Box>
        <Label>{p.label}</Label>
        <MultiSelect p={p} value={value} onChange={onChange} />
        <Help>{p.help}</Help>
      </Box>
    );
  }
  return (
    <TextField
      id={id}
      size="small"
      fullWidth
      label={p.label}
      multiline={p.type === "textarea"}
      minRows={p.type === "textarea" ? 5 : undefined}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value)}
      inputProps={{ dir: "auto" }}
      helperText={p.help}
    />
  );
}

export default function ParamForm({ tab, values, setValue, activeGeo, setActiveGeo, hasImage }) {
  const basic = tab.params.filter((p) => !p.advanced);
  const adv = tab.params.filter((p) => p.advanced);
  const field = (p) => <Field key={p.name} p={p} value={values[p.name]} onChange={(v) => setValue(p.name, v)}
    activeGeo={activeGeo} setActiveGeo={setActiveGeo} hasImage={hasImage} />;
  return (
    <Stack spacing={2.25}>
      {tab.custom_task && (
        <TextField
          id="p-model"
          select
          size="small"
          fullWidth
          label="Model"
          value={values.model || ""}
          onChange={(e) => setValue("model", e.target.value || null)}
          SelectProps={{ displayEmpty: true }}
          InputLabelProps={{ shrink: true }}
          helperText={<>Uses your own {tab.custom_task} weights if you pick them. <Link component={RouterLink} to="/models">Upload a model</Link></>}
        >
          <MenuItem value="">{tab.model_specs?.[0] ? `${tab.model_specs[0].name} (built-in)` : "Built-in"}</MenuItem>
          {tab.custom_models.map((m) => <MenuItem key={m.key} value={m.key}>{m.name}{m.public ? " (shared)" : ""}</MenuItem>)}
        </TextField>
      )}
      {basic.map(field)}
      {adv.length > 0 && (
        <Accordion variant="outlined" disableGutters sx={{ borderRadius: 2, "&:before": { display: "none" } }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle2">Advanced settings</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={2.25}>{adv.map(field)}</Stack>
          </AccordionDetails>
        </Accordion>
      )}
    </Stack>
  );
}
