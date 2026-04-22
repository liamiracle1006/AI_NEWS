declare module 'react-simple-maps' {
  import type { ReactNode, SVGProps, MouseEvent } from 'react'

  interface ComposableMapProps {
    projectionConfig?: Record<string, unknown>
    style?: React.CSSProperties
    children?: ReactNode
  }

  interface ZoomableGroupProps {
    zoom?: number
    minZoom?: number
    maxZoom?: number
    children?: ReactNode
  }

  interface GeographiesProps {
    geography: string | Record<string, unknown>
    children: (props: { geographies: Geography[] }) => ReactNode
  }

  interface Geography {
    rsmKey: string
    properties: Record<string, string>
    [key: string]: unknown
  }

  interface GeographyProps extends SVGProps<SVGPathElement> {
    geography: Geography
    fill?: string
    stroke?: string
    strokeWidth?: number
    style?: {
      default?: React.CSSProperties
      hover?: React.CSSProperties
      pressed?: React.CSSProperties
    }
    onMouseEnter?: (event: MouseEvent<SVGPathElement>) => void
    onMouseLeave?: (event: MouseEvent<SVGPathElement>) => void
    onClick?: (event: MouseEvent<SVGPathElement>) => void
  }

  export function ComposableMap(props: ComposableMapProps): JSX.Element
  export function ZoomableGroup(props: ZoomableGroupProps): JSX.Element
  export function Geographies(props: GeographiesProps): JSX.Element
  export function Geography(props: GeographyProps): JSX.Element
}
