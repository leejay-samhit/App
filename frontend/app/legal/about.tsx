// About us — content comes from Admin → Legal pages (kind "about") so the
// owner can edit it without a code change. Previously this screen was
// hardcoded, which is why admin edits never showed up.
import LegalPageView from "../../src/legal-page-view";

export default function About() {
  return <LegalPageView kind="about" title="About us" />;
}
