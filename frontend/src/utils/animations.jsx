import { useEffect, useRef } from "react";

export function useFadeUp() {
    const ref = useRef(null);
    useEffect(() => {
        const el = ref.current;
        if (!el) return;
        const obs = new IntersectionObserver(
            ([e]) => { if (e.isIntersecting) { el.classList.add("landing-visible"); obs.unobserve(el); } },
            { threshold: 0.12 }
        );
        obs.observe(el);
        return () => obs.disconnect();
    }, []);
    return ref;
}

export function FadeUp({ children, className = "", delay = 0, ...props }) {
    const ref = useFadeUp();
    return (
        <div ref={ref} className={`landing-fade-up ${className}`} style={{ transitionDelay: `${delay}s` }} {...props}>
            {children}
        </div>
    );
}
