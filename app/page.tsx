"use client";
import UserSearchForm from "@/components/filters/fontfilter-form";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const queryClient = new QueryClient();

export default function Home() {
  return (
    <div>
      <QueryClientProvider client={queryClient}>
        <UserSearchForm/>
      </QueryClientProvider>
    </div>
  );
}
