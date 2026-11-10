//+------------------------------------------------------------------+
//| FxbotOverlay.mq5                                                  |
//| Draws what the MoneyPrinter2 Python bot currently "sees":         |
//| Asian range box, sweep / BOS / breakout lines and a status panel. |
//| The bot writes  <Common>\Files\fxbot_<SYMBOL>.txt  every candle;  |
//| this indicator re-reads it every 2 seconds. Display only - it     |
//| never places or changes orders.                                   |
//+------------------------------------------------------------------+
#property copyright "MoneyPrinter2"
#property version   "1.00"
#property indicator_chart_window
#property indicator_plots 0

input int  RefreshSeconds = 2;
input int  FontSize       = 9;

const string PFX = "fxbot_";

int OnInit()
{
   EventSetTimer(MathMax(1, RefreshSeconds));
   Redraw();
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   ObjectsDeleteAll(0, PFX);
   Comment("");
}

int OnCalculate(const int rates_total, const int prev_calculated, const int begin,
                const double &price[])
{
   return(rates_total);
}

void OnTimer() { Redraw(); }

color ParseColor(string rgb)
{
   string p[];
   if(StringSplit(rgb, ',', p) != 3) return(clrWhite);
   return((color)(StringToInteger(p[0]) | (StringToInteger(p[1]) << 8) | (StringToInteger(p[2]) << 16)));
}

ENUM_LINE_STYLE ParseStyle(string s)
{
   if(s == "dash") return(STYLE_DASH);
   if(s == "dot")  return(STYLE_DOT);
   return(STYLE_SOLID);
}

void Redraw()
{
   string fname = "fxbot_" + _Symbol + ".txt";
   int h = FileOpen(fname, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON |
                           FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
   {
      Comment("fxbot overlay: no data for " + _Symbol + " yet (is run_live.py running for this pair?)");
      return;
   }
   ObjectsDeleteAll(0, PFX);
   string status = "";
   int n = 0;
   datetime now = TimeCurrent();
   while(!FileIsEnding(h))
   {
      string line = FileReadString(h);
      if(StringLen(line) == 0) continue;
      string f[];
      int k = StringSplit(line, '|', f);
      if(k < 2) continue;
      if(f[0] == "STATUS")
         status += f[1] + "\n";
      else if(f[0] == "HLINE" && k >= 5)
      {
         string nm = PFX + "h" + IntegerToString(n++);
         double pr = StringToDouble(f[1]);
         ObjectCreate(0, nm, OBJ_HLINE, 0, 0, pr);
         ObjectSetInteger(0, nm, OBJPROP_COLOR, ParseColor(f[2]));
         ObjectSetInteger(0, nm, OBJPROP_STYLE, ParseStyle(f[3]));
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         ObjectSetString(0, nm, OBJPROP_TOOLTIP, f[4] + " " + DoubleToString(pr, _Digits));
         string tl = nm + "t";
         ObjectCreate(0, tl, OBJ_TEXT, 0, now, pr);
         ObjectSetString(0, tl, OBJPROP_TEXT, "  " + f[4]);
         ObjectSetInteger(0, tl, OBJPROP_COLOR, ParseColor(f[2]));
         ObjectSetInteger(0, tl, OBJPROP_FONTSIZE, FontSize);
         ObjectSetInteger(0, tl, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
         ObjectSetInteger(0, tl, OBJPROP_SELECTABLE, false);
      }
      else if(f[0] == "BOX" && k >= 7)
      {
         string nm = PFX + "b" + IntegerToString(n++);
         datetime t1 = (datetime)StringToInteger(f[1]);
         datetime t2 = (datetime)StringToInteger(f[3]);
         ObjectCreate(0, nm, OBJ_RECTANGLE, 0, t1, StringToDouble(f[2]), t2, StringToDouble(f[4]));
         ObjectSetInteger(0, nm, OBJPROP_COLOR, ParseColor(f[5]));
         ObjectSetInteger(0, nm, OBJPROP_FILL, true);
         ObjectSetInteger(0, nm, OBJPROP_BACK, true);
         ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
         ObjectSetString(0, nm, OBJPROP_TOOLTIP, f[6]);
      }
   }
   FileClose(h);
   Comment(status);
   ChartRedraw();
}
