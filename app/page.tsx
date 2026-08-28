"use client";
import { useState } from "react";
import FontSearchForm from "@/components/filters/fontsearch-form";
import CytoscapeGraph from "@/components/graph/graph";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { BubbleFontResult } from "@/types/schema";
import { Footer, Header } from "@/components/ui/header-footer";

const queryClient = new QueryClient();

export default function Home() {
  const [bubbleResult, setBubbleResult] = useState<BubbleFontResult | null>(null);

  return (
    <QueryClientProvider client={queryClient}>
      {bubbleResult?._tag == "BubbleFontResult" && <CytoscapeGraph fontdata={bubbleResult} />}
      <div className="ui-overlay">
        <div className="col-stack">
          <Header/>
          <div className="row-stack">
            <FontSearchForm onBubbleResult={setBubbleResult} />
          </div>
          <Footer/>
        </div>
      </div>
    </QueryClientProvider>
  );
}