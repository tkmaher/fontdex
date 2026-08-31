import "@/app/styles/display.scss";
import { FontRow } from "@/types/schema";

export default function FontBlock({row, index, setter, selected}: {row: FontRow, index: number, setter: () => {}, selected: boolean}) {
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
                {row.font}
                <br/>
                {row.hits}
            </button>
        </div>
    )
}