import { FontResult, SiteResult } from "@/types/schema";

const PAGE_SIZE = 50;

export default function Pagination({
    submit,
    results,
    pageIn,
    disabled
}: {
    submit: (paging?: 'next' | 'back') => void,
    results: FontResult | SiteResult | undefined,
    pageIn: number,
    disabled: boolean
}) {
    return (
        <div className='pagination'>
          {results?._tag == "RowFontResult" || results?._tag == "SiteResult" ? 
            <>
              <button 
                className='text' 
                style={{
                  pointerEvents: (pageIn <= 1 || disabled) ? 'none' : 'all',
                  opacity: (pageIn <= 1 || disabled) ? '0.5' : '1'
                }}
                onClick={() => {
                  submit("back")
                }}
              >
                back
              </button>
              <div className='text'>
                {PAGE_SIZE * (pageIn - 1) + 1}-{Math.min(PAGE_SIZE * (pageIn), results?.rows)} of {results?.rows}
              </div> 
              
              <button 
                className='text'
                style={{
                  pointerEvents: (pageIn >= results?.pages || disabled) ? 'none' : 'all',
                  opacity: (pageIn >= results?.pages || disabled) ? '0.5' : '1'
                }}
                onClick={() => {
                  submit("next")
                }}
              >
                next
              </button>
            </> 
          : <div>
                loading...
            </div>
          }
        </div>
    )
}