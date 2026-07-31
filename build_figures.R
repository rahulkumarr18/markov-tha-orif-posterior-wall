suppressMessages({library(ggplot2); library(dplyr); library(forcats); library(scales)})
HERE <- "/Users/rahul/Desktop/Residency/Research 2/Acute THA vs ORIF for Geriatric Posterior Wall Acetabular Fxs Markov - Meir Marmor/JAAOS_Figures_Tables"
setwd(HERE)
theme_jaaos <- theme_classic(base_size = 11, base_family = "Arial") +
  theme(axis.text = element_text(color = "black"), legend.position = "bottom")

# ============================= Figure 1: Markov state map =============================
nodes <- data.frame(
  id = c("DISLOC_ORIF","WELL_ORIF","ORIF_SSI","REFRACTURE","CONV_THA","POST_REOP","REOP_TUN",
         "MEDCOMP","WELL_THA","DISLOC","PJI_E","PJI_L","ASEPTIC","REVT_A","POSTR_A","WELL_REV","REVT_S","POSTR_S","DEATH"),
  x = c(1,1,1,1, 2.7,2.7,2.7,  4.5,4.5, 5.7,6.0,6.0,4.7,  8.5,10.5,11.7,8.5,10.5, 13.1),
  y = c(7.4,5.4,3.4,1.4, 6.4,4.4,2.4,  7.4,5.2, 6.7,4.9,3.1,1.3,  6.6,6.6,4.0,1.6,1.6, 4.0),
  label = c("DISLOCATION\n(ORIF)","WELL\n(ORIF)","ORIF\nSSI","REFRACTURE","CONVERSION\nTHA","POST-ORIF\nREOP","ORIF REOP\n(TUNNEL)",
            "MEDICAL\nCOMPLICATION","WELL\n(THA)","DISLOCATION","PJI\nEARLY","PJI\nLATE","ASEPTIC\nLOOSENING",
            "REV TUNNEL\n(ASEPTIC)","POST-REV\n(ASEPTIC)","WELL\nREVISED","REV TUNNEL\n(SEPTIC)","POST-REV\n(SEPTIC)","DEATH"),
  grp = c(rep("ORIF",7), rep("THA",6), rep("REV",5), "Death"), stringsAsFactors=FALSE)
E <- function(f,t,ty) data.frame(from=f,to=t,type=ty,stringsAsFactors=FALSE)
edges <- rbind(
  E("WELL_ORIF","DISLOC_ORIF","fwd"),E("WELL_ORIF","ORIF_SSI","fwd"),E("WELL_ORIF","REFRACTURE","fwd"),
  E("ORIF_SSI","REOP_TUN","fwd"),E("REFRACTURE","REOP_TUN","fwd"),E("REOP_TUN","POST_REOP","fwd"),
  E("POST_REOP","WELL_ORIF","ret"),E("DISLOC_ORIF","WELL_ORIF","ret"),
  E("WELL_ORIF","CONV_THA","fwd"),E("CONV_THA","WELL_THA","fwd"),E("WELL_THA","MEDCOMP","fwd"),E("MEDCOMP","WELL_THA","ret"),
  E("WELL_THA","DISLOC","fwd"),E("WELL_THA","PJI_E","fwd"),E("PJI_E","PJI_L","fwd"),E("WELL_THA","ASEPTIC","fwd"),
  E("DISLOC","REVT_A","fwd"),E("ASEPTIC","REVT_A","fwd"),E("PJI_L","REVT_S","fwd"),E("PJI_E","REVT_S","fwd"),
  E("REVT_A","POSTR_A","fwd"),E("POSTR_A","WELL_REV","fwd"),E("REVT_S","POSTR_S","fwd"),E("POSTR_S","WELL_REV","fwd"),E("WELL_REV","DEATH","fwd"))
seg <- merge(merge(edges,nodes[,c("id","x","y")],by.x="from",by.y="id"),nodes[,c("id","x","y")],by.x="to",by.y="id",suffixes=c("",".e"))
names(seg)[names(seg)=="x.e"]<-"xend"; names(seg)[names(seg)=="y.e"]<-"yend"
zones <- data.frame(xmin=c(0.3,3.8,7.9),xmax=c(3.4,6.7,12.5),ymin=c(0.5,0.5,0.7),ymax=c(8.1,8.1,7.6),
                    zcol=c("#E4F3EF","#FCEEDD","#EFE8F8"),stringsAsFactors=FALSE)
pal <- c("ORIF"="#217B7B","THA"="#B8611F","REV"="#61509E","Death"="#111111")
p1 <- ggplot() +
  geom_rect(data=zones,aes(xmin=xmin,xmax=xmax,ymin=ymin,ymax=ymax),fill=zones$zcol,color="grey60",linetype="dashed",linewidth=.35)+
  geom_segment(data=subset(seg,type=="fwd"),aes(x=x,y=y,xend=xend,yend=yend),arrow=arrow(length=unit(.16,"cm"),type="closed"),linewidth=.5,color="grey28")+
  geom_segment(data=subset(seg,type=="ret"),aes(x=x,y=y,xend=xend,yend=yend),arrow=arrow(length=unit(.13,"cm"),type="closed"),linewidth=.4,color="grey48",linetype="22")+
  geom_label(data=nodes,aes(x=x,y=y,label=label,color=grp),fill="white",fontface="bold",size=2.85,
             family="Arial",label.padding=unit(.24,"lines"),label.r=unit(.15,"lines"),lineheight=.82,linewidth=.85)+
  scale_color_manual(values=pal,guide="none")+
  annotate("text",x=c(1.85,5.15,10.2),y=8.62,label=c("ORIF-native","Primary / converted THA","Revision"),
           hjust=0.5,fontface="bold",size=3.1,family="Arial",color=c("#217B7B","#B8611F","#61509E"))+
  coord_equal(xlim=c(0.2,14.0),ylim=c(0.2,8.9),clip="off")+theme_void(base_family="Arial")+theme(plot.margin=margin(4,4,4,4))
ggsave("Figure1_StateMap.tiff", p1, width=7.0, height=3.9, dpi=600, compression="lzw", bg="white")
ggsave("Figure1_StateMap.png",  p1, width=7.0, height=3.9, dpi=600, bg="white")
cat("Figure 1 saved\n")

# ============================= Figure 2: One-way sensitivity (tornado) =============================
d2 <- read.csv("oneway_sensitivity_export.csv")
base_inmb <- d2$base_inmb[1]
d2 <- d2 %>% mutate(range_width = abs(high_inmb - low_inmb),
                     parameter = fct_reorder(parameter, range_width))
p2 <- ggplot(d2) +
  geom_vline(xintercept = base_inmb, linetype = "dashed", linewidth = .45, color="grey30") +
  geom_rect(aes(xmin = pmin(low_inmb,high_inmb), xmax = pmax(low_inmb,high_inmb),
                ymin = as.numeric(parameter)-.38, ymax = as.numeric(parameter)+.38),
            fill = "#2C6E9B", color = "#154569", linewidth = .3) +
  scale_x_continuous("10-year incremental net monetary benefit, acute THA vs ORIF (USD)",
                     labels = label_dollar(scale = 1e-6, suffix = "M")) +
  scale_y_continuous(NULL, breaks = seq_along(levels(d2$parameter)), labels = levels(d2$parameter)) +
  theme_jaaos + theme(legend.position="none")
ggsave("Figure2_OneWaySensitivity.tiff", p2, width=7.0, height=4.0, dpi=600, compression="lzw", bg="white")
ggsave("Figure2_OneWaySensitivity.png",  p2, width=7.0, height=4.0, dpi=600, bg="white")
cat("Figure 2 saved\n")

# ============================= Figures 3-4: Two-way sensitivity grids =============================
two_way <- function(csv, xcol, ycol, xlab, ylab, bx, by, outfile, xdollar=FALSE, ydollar=FALSE){
  d <- read.csv(csv)
  d$preferred <- ifelse(d$inmb >= 0, "THA", "ORIF")
  d$preferred <- factor(d$preferred, levels=c("THA","ORIF"))
  p <- ggplot(d, aes(.data[[xcol]], .data[[ycol]], fill = preferred)) +
    geom_raster() +
    annotate("point", x = bx, y = by, shape = 4, size = 3, stroke = 1.3, color = "black") +
    annotate("text",  x = bx, y = by, label = "Baseline", hjust = -0.15, vjust = -0.5, size = 3.2, family="Arial") +
    scale_fill_manual(values = c(THA = "#2C6E9B", ORIF = "#C0392B"),
                      labels = c("Acute THA preferred","ORIF preferred"), name = NULL) +
    labs(x = xlab, y = ylab) + theme_jaaos
  if (xdollar) p <- p + scale_x_continuous(labels = label_dollar())
  if (ydollar) p <- p + scale_y_continuous(labels = label_dollar())
  ggsave(paste0(outfile,".tiff"), p, width=5.0, height=4.6, dpi=600, compression="lzw", bg="white")
  ggsave(paste0(outfile,".png"),  p, width=5.0, height=4.6, dpi=600, bg="white")
}
two_way("twoway_utility_export.csv", "orif_util","tha_util", "ORIF well-state utility", "THA well-state utility",
        bx=0.74, by=0.81, outfile="Figure3_TwoWayUtilities")
two_way("twoway_cost_export.csv", "orif_cost","tha_cost", "ORIF index cost (USD)", "THA index cost (USD)",
        bx=47207, by=40994, outfile="Figure4_TwoWayCosts", xdollar=TRUE, ydollar=TRUE)
cat("Figures 3-4 saved\n")
cat("ALL DONE\n")
