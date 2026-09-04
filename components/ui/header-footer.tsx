"use client;"
import { useEffect, useState } from "react";
import About from "./about";

export function Header() {
    const header = "Fonts-Index";
    const a = 2;
    const p = 500;
    const [ count, setCount ] = useState(0);
    const [ bigCount, setBigCount ] = useState(0);
    const [ activated, setActivated ] = useState(false);

    const [ aboutHidden, setAboutHidden ] = useState(true);

    useEffect(() => {
        const intervalId = setInterval(() => {
            setCount((prevCount) => (prevCount + 1));
            if (count % 2 == 0)
                setBigCount((prevCount) => (prevCount + 1) % 31);
        }, 50);
    
        return () => clearInterval(intervalId);
    })

    return (
        <>
            <div className="header-row">
                <div className="header-row">
                    <button type="button" className={`text img-btn ${activated && 'button-rev'}`} onClick={() => setActivated(!activated)}>
                        {activated ? '⏸' : '▶'}
                    </button>
                    <div className="text">
                        {[...header].map((char, index) => (
                            <span 
                                className="char-span-title"
                                key={index}
                                style={{
                                    fontStyle: activated ? ((bigCount + index) % 4 == 0) ? "italic" : undefined : undefined,
                                    fontWeight: activated ? ((bigCount + index) % 5 == 0) ? "bold" : ((bigCount + index) % 3 == 0) ? "bolder" : undefined : undefined,
                                    paddingRight: 
                                        activated ? index != header.length - 1 ?
                                        `${ 4 * a / p * Math.abs(((((count + index + char.charCodeAt(0)) - p / 4) % p) + p) % p - p / 2)}px`
                                        : undefined : undefined
                                }}
                            >
                                {char}
                            </span>
                        ))}
                    </div>
                </div>
                <div className="header-row">
                    <div className="text">
                        Statistics
                    </div>
                    <button className="text" onClick={() => setAboutHidden(!aboutHidden)}>
                        About
                    </button>
                </div>
            </div>
            <About hidden={aboutHidden} setAboutHidden={setAboutHidden}/>
        </>
    )
}

export function Footer() {
    // TODO: increment animation for numbers
    return (
        <div className="footer-row">
            <div className="footer-row">
                <div className="text">
                XXX fonts cataloged
                </div>
                <div className="text">
                XXX sites cataloged
                </div>
            </div>
            <div className="text" style={{flexGrow: 1}}></div>
            <div className="text">
                Archived August 2026
            </div>
        </div>
        
    )
}