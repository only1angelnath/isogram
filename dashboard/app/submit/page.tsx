import type { Metadata } from "next";
import { getApiBaseUrlForBadge } from "@/lib/api";
import { SubmitForm } from "@/components/SubmitForm";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Submit a project",
  description: "Is your contract missing from Isogram? Propose it for listing. Every submission is reviewed by a person.",
};

export default function SubmitPage() {
  let base = "https://isogramapi.onrender.com";
  try { base = getApiBaseUrlForBadge(); } catch { /* keep the default */ }
  return (
    <main className="container section first">
      <div className="page-head">
        <div className="eyebrow">Submit</div>
        <h1>Add your project to Isogram.</h1>
        <p className="lede">
          Isogram finds active contracts on its own, but it can miss some. Send yours and a person will review it.
          Nothing is listed automatically, and the address is the only required field.
        </p>
      </div>
      <SubmitForm apiBase={base} />
      <p className="iso-dim" style={{ maxWidth: 560, fontSize: 13, lineHeight: 1.6, marginTop: 16 }}>
        Builders can also use the same endpoint directly: see <a href="/docs/api#submit">POST /submit</a> in the API reference.
      </p>
    </main>
  );
}
