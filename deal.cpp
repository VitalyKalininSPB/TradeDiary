include "deal.h"
#include "ui_deal.h"

Deal::Deal(QWidget *parent) :
    QDialog(parent),
    ui(new Ui::Deal)
{
    ui->setupUi(this);
}

Deal::~Deal()
{
    delete ui;
}
