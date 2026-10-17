import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <div className="wrap narrow">
      <h1 className="page-title">Page not found</h1>
      <p><Link to="/">Back to the catalog</Link></p>
    </div>
  );
}
