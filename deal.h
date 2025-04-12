#ifndef DEAL_H
#define DEAL_H

#include <QDialog>

namespace Ui {
class Deal;
}

class Deal : public QDialog
{
    Q_OBJECT

public:
    explicit Deal(QWidget *parent = nullptr);
    ~Deal();

private:
    Ui::Deal *ui;
};

#endif // DEAL_H
