import { Link as RouterLink } from "react-router-dom";
import Button from "@mui/material/Button";
import SearchOffIcon from "@mui/icons-material/SearchOff";
import { EmptyState } from "../components/DataStates";

export default function NotFound() {
  return (
    <EmptyState
      icon={<SearchOffIcon fontSize="inherit" />}
      title="Page not found"
      description="The link may be old, or the page was moved."
      action={<Button component={RouterLink} to="/" variant="contained">Back to the catalog</Button>}
    />
  );
}
