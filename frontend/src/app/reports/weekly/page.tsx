import { redirect } from "next/navigation";

export default function WeeklyReportListRedirect() {
  redirect("/reports?tab=weekly");
}
