import geopandas as gpd
import polyline
from shapely.geometry import LineString
import requests
from io import BytesIO

# Step 1: Decode the Google polyline
google_polyline = "ebm}Gyrml@fA_BpD}L`AuCZm@pAkDlBwFrBeF`FgHrLaTzDyGXO^}@~DgFxEeFjIcIjEeD~Aw@j@e@bBoCb@a@|Aw@~B_@tAe@`BiAxFcFxAeAv@OdADtAOfFoEr@Ql@LbAj@j@j@LZnAxD^tFPj@f@^dCVx@l@r@fBOh@PJDVHg@HFx@xB|@|Ct@dBh@p@l@BZUPo@tAmJ^mBp@cBz@yArAgEf@yEjB_K`BmDTKRFTGzAsBfAwBnBeFjAwBhAmAbCsA~Ca@zBeApDsBlAa@lC]~DaBnDeAvFeDtCwBdB{ArLgMdBkAnBy@hBg@xBg@xBSvBTpAn@rErCfCdAxAb@nKlB`F`CfBn@xRfDbLhADZG|@UbAcCnEq@p@cBv@cDJgAReA`@{BhByB|Cm@^gBd@eAv@a@jAo@`Do@rDSrBOj@qBpDAXGERNx@fBrEjFhAf@vEfAzDWhHY~G@`AYxByBvC\\dBt@J^GdIPbA`A~D`@nAfCdGv@rChAhBh@tA|BrHtAlFfAtCb@pBAfBBLVPvAZPPJ`@An@]jDExB@nDNlBRz@`@dAfDxD`@r@ZpDTx@ZZ~@RXKj@g@XPGXWTwA~@gA`Aa@bAc@dB_DfGqCfGw@nBw@vCm@xD[bEWjHSbBs@|B}FfMk@dCOhC?lEU`Cy@hCiErGaAjBeBxH{@jCuFxLoB`GcAzE]j@c@ZmDZy@h@OTWr@QxAEpC[jBKV]h@c@\\mChBiFbIyBpFOt@a@|D_@v@yAtAcBtBe@b@mAVHKQd@L`AtAdCVnAn@bHJbCAp@ObCWzAiCvI{AxJ?~ANnCi@dG?~@^`DBbAK~Aa@hBg@v@oA|@Sb@E|@vApT@fBk@~KIxCStBGfDH^xA|@Xf@lAbETjA?p@Ip@_DxIeAxAGrBPhDMf@]Da@a@aH{JyP{SyAgAcFwB{AmAcAsA}EyHm@o@sWoTwEyE_D{@oAAwATwAt@yNdLsAv@qANgIoAoEqAoGEsMcEmB]_CQyBg@cCiAmB}AyAcBiEgGkCuC{AiBy@qAuFwLoAeCi@aBuDyMmA_CsA_ByAgAqBcAw@t@s@`@_@Fo@M]ScCcC_Bq@w@k@_@w@mCeEWm@iBiByK{FiEiCyDeBeAY{C_BkAsAi@y@YGsAmAeDaCoCqCmAyA}HwEkIeHKS{@c@oCuBoC_DkDiGo@s@yAiA{@iAyAqEu@aBM?e@hAKHm@_Ac@Y"
decoded_coords = polyline.decode(google_polyline)  # returns list of (lat, lon)

# Flip to (lon, lat) for Shapely
line = LineString([(lon, lat) for lat, lon in decoded_coords])

# Step 2: Load the municipality boundaries from the URL
geo_df = gpd.read_file("municipality.json")

# Step 3: Check intersection with each municipality
intersections = geo_df[geo_df.geometry.intersects(line)]

if not intersections.empty:
    print("Polyline intersects the following municipalities:")
    print(intersections[["NAME", "geometry"]])
else:
    print("Polyline does not intersect any municipality.")
