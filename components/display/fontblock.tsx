import "@/app/styles/display.scss";
import { FontRow, SiteRow } from "@/types/schema";

export default function Block({
    row, 
    index, 
    setter, 
    selected
}: {
    row: FontRow | SiteRow, 
    index: number, 
    setter: () => {}, 
    selected: boolean
}) {
    return (
        <div className="font-block">
            <button 
                className={`
                    text
                    ${selected ? 'button-img-rev' :
                    index % 3 == 1 ? 'button-not' : index % 3 == 2 ? 'button-img' : ''
                    }
                `}
                onClick={() => setter()}
            >
                {row._tag == "FontRow" ? row.font : row.domain}
                <br/>
                {row._tag == "FontRow" ? row.hits : row.rank}
            </button>
        </div>
    )
}