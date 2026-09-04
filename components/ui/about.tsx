import { all } from "effect/Equivalence";

export default function About({
    hidden, 
    setAboutHidden
}: {
    hidden: boolean,
    setAboutHidden: (hidden: boolean) => void
}) {
    return (
        <div className={`about ${hidden ? '' : 'about-unhidden'}`}>
            <div className="about-bg"/>
            <button className="img-btn" onClick={() => setAboutHidden(true)}>
                ×
            </button>
            <div className="about-box">
                test
            </div> 
        </div>
    )
}