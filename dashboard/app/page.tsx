"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

/** Client-side redirect so the static export works without a server. */
export default function Home() {
  const router = useRouter();
  useEffect(() => { router.replace("/login"); }, [router]);
  return <div className="pn-root min-h-screen" />;
}
