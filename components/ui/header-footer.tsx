"use client;"
import { useEffect, useState } from "react";

export function Header() {
    // TODO: animation for title
    const header = "Fonts-Index";
    const a = 20;
    const p = 500;
    const [ count, setCount ] = useState(0);
    const [ bigCount, setBigCount ] = useState(0);

    useEffect(() => {
        const intervalId = setInterval(() => {
            setCount((prevCount) => (prevCount + 1));
            if (count % 2 == 0)
                setBigCount((prevCount) => (prevCount + 1) % 31);
        }, 50);
    
        return () => clearInterval(intervalId);
    })

    return (
        <div className="header-row">
            <div className="text">
                {[...header].map((char, index) => (
                    <span 
                        className="char-span-title"
                        key={index}
                        style={{
                            fontStyle: ((bigCount + index) % 4 == 0) ? "italic" : undefined,
                            fontWeight: ((bigCount + index) % 5 == 0) ? "bold" : ((bigCount + index) % 3 == 0) ? "bolder" : undefined,
                            paddingRight: 
                                index != header.length - 1 ?
                                `${3 + 4 * a / p * Math.abs(((((count + index + char.charCodeAt(0)) - p / 4) % p) + p) % p - p / 2)}px`
                                : undefined
                        }}
                    >
                        {char}
                    </span>
                ))}
            </div>
            <div className="header-row">
                <div className="text">
                    Statistics
                </div>
                <div className="text">
                    About
                </div>
            </div>
        </div>
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
            <div className="text">
            Archived August 2026
            </div>
        </div>
        
    )
}